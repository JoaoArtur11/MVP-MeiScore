import duckdb
import sys

from project_paths import DB_PATH, get_rfb_files


def sql_list(files):
    return "[" + ",".join("'" + f.replace("'", "''") + "'" for f in files) + "]"


def main():
    emp_files = get_rfb_files("empresas")
    if not emp_files:
        raise RuntimeError("Nao encontrei arquivos de EMPRESAS em 'dados cnae'/'rf_cnpj_csv'.")

    con = duckdb.connect(str(DB_PATH))
    con.execute("PRAGMA threads=8;")

    files_sql = sql_list(emp_files)
    con.execute("DROP TABLE IF EXISTS empresas;")
    con.execute(
        f"""
        CREATE TABLE empresas AS
        SELECT * FROM read_csv_auto(
            {files_sql},
            sep=';',
            header=false,
            encoding='latin-1',
            union_by_name=true,
            strict_mode=false,
            all_varchar=true,
            ignore_errors=true
        );
    """
    )

    print("COUNT empresas:", con.execute("SELECT COUNT(*) FROM empresas").fetchone()[0])
    con.close()
    print("OK empresas (header=false)")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("ERRO:", e)
        sys.exit(1)
