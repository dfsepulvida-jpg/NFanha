import re
import io
import pandas as pd
import pdfplumber

EXPECTED_COLUMNS = [
    "CODIGO",
    "DESCRICAO",
    "QUANT.",
    "V. UNIT.",
    "V. TOTAL."
]

# Produtos que devem ser reconhecidos como código de peça (incluindo as novas regras)
PRODUCT_KEYWORDS = [
    "VR", "DG", "CS", "SC", "DT", "PNS", "BORDA", "BT", "FC", "ZD", "PL", "FG", "PLACAS", "SAC", "EP", "PT", "BORDA CONCRETADA",
    "PNSTR8X35", "LAJE PAINEL", "PAINEL",
    "PRE-MOLDADO FORMA", "PRE LAJE - AÇO", "PRE MOLDADO - AÇO", "AB"
]

# Monta regex para todos os produtos, aceita também qualquer item contendo "PNS" ou "LAJE PAINEL", "LAJE", "PAINEL"
PRODUCT_REGEX_TERMS = '|'.join([re.escape(key) for key in PRODUCT_KEYWORDS])
CODIGO_REGEX = re.compile(
    fr'\b({PRODUCT_REGEX_TERMS})\b[-/]?\d{{0,6}}|\d+\s*PLACAS|\d+\s*PNS|PNS[^\s]*',
    re.I
)

def is_laje_painel(txt):
    txt_norm = txt.upper().replace('Á','A').replace('É','E').replace('Í','I').replace('Ó','O').replace('Ú','U').replace('Ç','C')
    return (
        "LAJE PAINEL" in txt_norm or
        "LAJE" in txt_norm or
        "PAINEL" in txt_norm
    )

def is_pre_moldado(txt):
    txt_norm = txt.upper().replace('Á','A').replace('É','E').replace('Í','I').replace('Ó','O').replace('Ú','U').replace('Ç','C')
    return (
        "PRE-MOLDADO FORMA" in txt_norm or
        "PRE LAJE - AÇO" in txt_norm or
        "PRE MOLDADO - AÇO" in txt_norm
    )

def is_ab(txt):
    return "AB" in txt.upper()

def parse_number(s):
    if s is None:
        return None
    s = str(s).strip()
    if s == "" or s in ["-", "–"]:
        return None
    negative = False
    if s.startswith("(") and s.endswith(")"):
        negative = True
        s = s[1:-1].strip()
    s = s.replace("R$", "").replace("$", "").replace("\u00A0", "").strip()
    if re.search(r'[eE]', s):
        s_norm = s.replace(',', '.')
        s_norm = re.sub(r'[^0-9\.\-eE\+]', '', s_norm)
        try:
            v = float(s_norm)
            return -v if negative else v
        except:
            return None
    if '.' in s and ',' in s:
        s2 = s.replace('.', '').replace(',', '.')
    else:
        if ',' in s and '.' not in s:
            s2 = s.replace(',', '.')
        elif '.' in s and ',' not in s:
            if s.count('.') > 1:
                s2 = s.replace('.', '')
            else:
                s2 = s
        else:
            s2 = s
    s2 = re.sub(r'[^0-9\.\-]', '', s2)
    if s2 in ['', '.', '-', '-.']:
        return None
    try:
        v = float(s2)
        return -v if negative else v
    except:
        return None

def format_number_br(v, always_decimal=False):
    if v is None or v == "":
        return ""
    try:
        if isinstance(v, str):
            v = float(v.replace(",", "."))
        if always_decimal:
            s = f"{v:,.2f}"
            s = s.replace(',', 'X').replace('.', ',').replace('X', '.')
            return s
        else:
            if float(v).is_integer():
                return str(int(round(v)))
            else:
                s = f"{v:,.2f}"
                s = s.replace(',', 'X').replace('.', ',').replace('X', '.')
                s = re.sub(r',(\d)0$', r',\1', s)
                return s
    except Exception:
        return ""

def extract_os_from_tokens(words):
    candidate = None
    min_top = None
    for w in words:
        x0 = w['x0']
        top = w['top']
        txt = w['text'].strip()
        if re.fullmatch(r'\d{4,6}', txt) and x0 < 60 and top > 700:
            if (min_top is None) or (top > min_top):
                candidate = txt
                min_top = top
    return candidate if candidate else ""

def extract_from_pdf_bytes(b: bytes, filename="") -> pd.DataFrame:
    items = []
    os_code = ""
    with pdfplumber.open(io.BytesIO(b)) as pdf:
        for page in pdf.pages:
            words = page.extract_words(use_text_flow=True) or page.extract_words()
            if not os_code:
                os_code = extract_os_from_tokens(words)
            lines = {}
            for w in words:
                cy = round((w['top']+w['bottom'])/2)
                lines.setdefault(cy, []).append(w)
            for cy in sorted(lines.keys()):
                ws = lines[cy]
                d = {}
                descr = []
                for w in ws:
                    x0 = w['x0']
                    txt = w['text'].strip()
                    # Código da peça (inclui LAJE PAINEL, LAJE, PAINEL, PRE-MOLDADO, AB, PNS)
                    if (
                        (60 <= x0 <= 100 and CODIGO_REGEX.search(txt))
                        or CODIGO_REGEX.fullmatch(txt)
                        or "PNS" in txt.upper()
                        or is_laje_painel(txt)
                        or is_pre_moldado(txt)
                        or is_ab(txt)
                    ):
                        d['CODIGO'] = txt
                    elif 320 <= x0 <= 330 and re.match(r'\d+', txt):
                        d['QUANT.'] = txt
                    elif 340 <= x0 <= 370 and re.match(r'[\d.,]+', txt):
                        d['V. UNIT.'] = txt
                    elif 394 <= x0 <= 460 and re.match(r'[\d.,]+', txt):
                        d['V. TOTAL.'] = txt
                    elif 100 < x0 < 300:
                        descr.append(txt)
                # Equações inteligentes para preencher campos faltantes
                quant = parse_number(d.get('QUANT.'))
                unit = parse_number(d.get('V. UNIT.'))
                total = parse_number(d.get('V. TOTAL.'))
                descricao = " ".join(descr).strip()
                # Preenchimento de campos
                # 1. Se todos presentes, não faz nada
                # 2. Se só quantidade e unitário, calcula total
                if quant is not None and unit is not None and (total is None or total == 0):
                    total = quant * unit
                # 3. Se só quantidade e total, calcula unitário
                if quant is not None and total is not None and (unit is None or unit == 0):
                    if quant != 0:
                        unit = total / quant
                # 4. Se só unitário e total, calcula quantidade
                if (quant is None or quant == 0) and unit is not None and total is not None:
                    if unit != 0:
                        quant = total / unit
                # 5. Se só quantidade, não faz nada
                # 6. Se só unitário, não faz nada
                # 7. Se só total, não faz nada
                # 8. Se tudo vazio, ignora linha
                # Só adiciona se tiver pelo menos código e um dos campos
                if d.get('CODIGO') and (quant is not None or unit is not None or total is not None):
                    items.append({
                        "CODIGO": d.get('CODIGO', ""),
                        "DESCRICAO": descricao,
                        "QUANT.": format_number_br(quant, always_decimal=False),
                        "V. UNIT.": format_number_br(unit, always_decimal=True),
                        "V. TOTAL.": format_number_br(total, always_decimal=True)
                    })
    df = pd.DataFrame(items)
    nf_code = ""
    m = re.search(r'(\d{4,})', filename)
    if m:
        nf_code = m.group(1)
    df.insert(0, 'NF', nf_code)
    df.insert(1, 'OS', os_code)
    for col in ['NF', 'OS', 'CODIGO', 'DESCRICAO', 'QUANT.', 'V. UNIT.', 'V. TOTAL.']:
        if col not in df.columns:
            df[col] = ""
    return df[['NF', 'OS', 'CODIGO', 'DESCRICAO', 'QUANT.', 'V. UNIT.', 'V. TOTAL.']]

def process_bytes_files(files):
    out_list = []
    for f in files:
        fn = f.get('filename', '') or ''
        b = f.get('bytes', b'') or b''
        df = extract_from_pdf_bytes(b, filename=fn)
        if df is None or df.empty:
            continue
        out_list.append(df)
    if out_list:
        combined = pd.concat(out_list, ignore_index=True, sort=False)
        for col in ['NF', 'OS', 'CODIGO', 'DESCRICAO', 'QUANT.', 'V. UNIT.', 'V. TOTAL.']:
            if col not in combined.columns:
                combined[col] = ""
        return combined[['NF', 'OS', 'CODIGO', 'DESCRICAO', 'QUANT.', 'V. UNIT.', 'V. TOTAL.']]
    else:
        return pd.DataFrame(columns=['NF','OS','CODIGO','DESCRICAO','QUANT.','V. UNIT.','V. TOTAL.'])

if __name__ == "__main__":
    import sys, os
    if len(sys.argv) < 2:
        print("Uso: python extractor.py <arquivo.pdf>")
        sys.exit(1)
    path = sys.argv[1]
    if not os.path.exists(path):
        print("Arquivo não encontrado:", path)
        sys.exit(2)
    with open(path, "rb") as fh:
        b = fh.read()
    df = process_bytes_files([{"filename": os.path.basename(path), "bytes": b}])
    out_csv = os.path.splitext(os.path.basename(path))[0] + "_extracted.csv"
    df.to_csv(out_csv, index=False, sep=';', encoding='utf-8')
    print("Extração concluída. CSV salvo em", out_csv)