import duckdb
import sys

from project_paths import DB_PATH, get_rfb_files


def main():
    simples_files = get_rfb_files("simples")
    if not simples_files:
        raise RuntimeError("Nao encontrei arquivos de SIMPLES.")

    simples_file = simples_files[0]

    con = duckdb.connect(str(DB_PATH))
    con.execute("PRAGMA threads=8;")

    con.execute("DROP TABLE IF EXISTS simples;")
    con.execute(
        f"""
        CREATE TABLE simples AS
        SELECT * FROM read_csv_auto(
            '{str(simples_file).replace("'", "''")}',
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

    print("COUNT simples:", con.execute("SELECT COUNT(*) FROM simples").fetchone()[0])
    con.close()
    print("OK simples (header=false)")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("ERRO:", e)
        sys.exit(1)
