import duckdb
from pathlib import Path

from project_paths import DB_PATH, get_rfb_files

def detect_encoding(path: str) -> str:
    """
    Detecção simples e eficiente:
    - Se tiver BOM UTF-16 ou muitos bytes nulos -> UTF-16
    - Senão, tenta UTF-8; se falhar -> latin-1
    """
    p = Path(path)
    raw = p.read_bytes()[:20000]

    # BOM UTF-16
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        return "utf-16"

    # Muitos NULs (característica forte de UTF-16)
    if raw.count(b"\x00") > 50:
        return "utf-16"

    # Tenta UTF-8
    try:
        raw.decode("utf-8")
        return "utf-8"
    except UnicodeDecodeError:
        return "latin-1"

def sql_list(files):
    return "[" + ",".join("'" + f.replace("'", "''") + "'" for f in files) + "]"

def create_empresas(con, emp_files):
    files_sql = sql_list(emp_files)
    con.execute("DROP TABLE IF EXISTS empresas;")
    con.execute(f"""
        CREATE TABLE empresas AS
        SELECT * FROM read_csv_auto(
            {files_sql},
            sep=';',
            header=true,
            encoding='latin-1',
            union_by_name=true
        );
    """)
    print("✅ empresas OK (latin-1)")

def create_simples(con, simples_file):
    con.execute("DROP TABLE IF EXISTS simples;")
    con.execute(f"""
        CREATE TABLE simples AS
        SELECT * FROM read_csv_auto(
            '{str(simples_file).replace("'", "''")}',
            sep=';',
            header=true,
            encoding='latin-1',
            union_by_name=true
        );
    """)
    print("✅ simples OK (latin-1)")

from pathlib import Path

def try_read_into_table(con, table_name: str, file_path: str, create: bool):
    """
    Tenta ler um arquivo com uma lista de encodings.
    Se criar tabela: CREATE TABLE AS SELECT...
    Se inserir: INSERT INTO ... SELECT...
    """
    f = file_path.replace("'", "''")
    base_sql = f"""
        read_csv_auto(
            '{f}',
            sep=';',
            header=true,
            union_by_name=true,
            strict_mode=false
        )
    """

    # Ordem pensada para seu cenário:
    # 1) latin-1 (funcionou em empresas e costuma funcionar em muitos estabelecimentos)
    # 2) utf-16 (resolve arquivos com BOM/nulos)
    # 3) utf-8 (se realmente for)
    attempts = [
        ("latin-1", False),
        ("utf-16", False),
        ("utf-8",  False),

        # fallback com ignore_errors=true (só se todos falharem)
        ("latin-1", True),
        ("utf-16", True),
        ("utf-8",  True),
    ]

    last_err = None
    for enc, ignore in attempts:
        try:
            enc_sql = f"encoding='{enc}',"
            ign_sql = "ignore_errors=true," if ignore else ""
            select_sql = f"""
                SELECT * FROM read_csv_auto(
                    '{f}',
                    sep=';',
                    header=true,
                    {enc_sql}
                    {ign_sql}
                    union_by_name=true,
                    strict_mode=false
                )
            """

            if create:
                con.execute(f"CREATE TABLE {table_name} AS {select_sql};")
            else:
                con.execute(f"INSERT INTO {table_name} {select_sql};")

            print(f"✅ {Path(file_path).name} OK (enc={enc}, ignore={ignore})")
            return

        except Exception as e:
            last_err = e

    raise RuntimeError(f"Falhou em {file_path}: {last_err}")

def create_estabelecimentos_incremental(con, est_files):
    con.execute("DROP TABLE IF EXISTS estabelecimentos;")

    # cria schema a partir do primeiro arquivo (mas agora tentando encodings de verdade)
    first = est_files[0]
    print("-> Criando tabela estabelecimentos a partir de:", Path(first).name)
    try_read_into_table(con, "estabelecimentos", first, create=True)

    # insere o resto
    for f in est_files[1:]:
        print("-> Inserindo:", Path(f).name)
        try_read_into_table(con, "estabelecimentos", f, create=False)

    print("✅ estabelecimentos OK (incremental robusto)")

    con.execute("DROP TABLE IF EXISTS estabelecimentos;")

    # cria a tabela a partir do primeiro arquivo (para fixar schema)
    first = est_files[0]
    enc_first = detect_encoding(first)
    print(f"-> Schema base: {Path(first).name} ({enc_first})")

    con.execute(f"""
        CREATE TABLE estabelecimentos AS
        SELECT * FROM read_csv_auto(
            '{first.replace("'", "''")}',
            sep=';',
            header=true,
            encoding='{enc_first}',
            union_by_name=true,
            strict_mode=false
        );
    """)

    # insere os demais
    for f in est_files[1:]:
        enc = detect_encoding(f)
        print(f"-> Inserindo: {Path(f).name} ({enc})")
        con.execute(f"""
            INSERT INTO estabelecimentos
            SELECT * FROM read_csv_auto(
                '{f.replace("'", "''")}',
                sep=';',
                header=true,
                encoding='{enc}',
                union_by_name=true,
                strict_mode=false
            );
        """)

    print("✅ estabelecimentos OK (incremental)")

def main():
    emp_files = get_rfb_files("empresas")
    est_files = get_rfb_files("estabelecimentos")
    simples_files = get_rfb_files("simples")

    print("EMPRESAS:", len(emp_files), "ex:", emp_files[0] if emp_files else None)
    print("ESTABELECIMENTOS:", len(est_files), "ex:", est_files[0] if est_files else None)
    print("SIMPLES:", len(simples_files), "ex:", simples_files[0] if simples_files else None)

    if not emp_files or not est_files or not simples_files:
        raise RuntimeError("Faltam arquivos (empresas/estabelecimentos/simples).")

    con = duckdb.connect(str(DB_PATH))
    con.execute("PRAGMA threads=8;")

    create_empresas(con, emp_files)
    create_estabelecimentos_incremental(con, est_files)
    create_simples(con, simples_files[0])

    # sanity check
    print("COUNT empresas:", con.execute("SELECT COUNT(*) FROM empresas").fetchone()[0])
    print("COUNT estabelecimentos:", con.execute("SELECT COUNT(*) FROM estabelecimentos").fetchone()[0])
    print("COUNT simples:", con.execute("SELECT COUNT(*) FROM simples").fetchone()[0])

    con.close()
    print("✅ DuckDB pronto em:", DB_PATH)

if __name__ == "__main__":
    main()
