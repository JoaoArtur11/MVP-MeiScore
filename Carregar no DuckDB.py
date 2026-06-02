import duckdb

from project_paths import DB_PATH, get_rfb_files


def create_from_files(con, table, files):
    files_sql = "[" + ",".join("'" + f.replace("'", "''") + "'" for f in files) + "]"
    con.execute(f"DROP TABLE IF EXISTS {table};")

    attempts = [
        ("AUTO", ""),
        ("UTF8", "encoding='utf-8',"),
        ("LATIN1", "encoding='latin-1',"),
    ]

    last_err = None
    for label, enc_sql in attempts:
        try:
            print(f"-> Criando {table} com {label}")
            con.execute(
                f"""
                CREATE TABLE {table} AS
                SELECT * FROM read_csv_auto(
                    {files_sql},
                    sep=';',
                    header=true,
                    {enc_sql}
                    union_by_name=true
                );
            """
            )
            print(f"OK {table} ({label})")
            return
        except Exception as e:
            print(f"   falhou ({label}): {e}")
            last_err = e

    raise last_err


def main():
    emp_files = get_rfb_files("empresas")
    est_files = get_rfb_files("estabelecimentos")
    sim_files = get_rfb_files("simples")

    print("EMPRESAS:", len(emp_files))
    if emp_files:
        print("  ex:", emp_files[0])
    print("ESTABELECIMENTOS:", len(est_files))
    if est_files:
        print("  ex:", est_files[0])
    print("SIMPLES:", len(sim_files))
    if sim_files:
        print("  ex:", sim_files[0])

    if not emp_files:
        raise RuntimeError("Nao encontrei arquivos de EMPRESAS.")
    if not est_files:
        raise RuntimeError("Nao encontrei arquivos de ESTABELECIMENTOS.")
    if not sim_files:
        raise RuntimeError("Nao encontrei arquivo de SIMPLES/MEI.")

    con = duckdb.connect(str(DB_PATH))
    con.execute("PRAGMA threads=8;")

    create_from_files(con, "empresas", emp_files)
    create_from_files(con, "estabelecimentos", est_files)
    create_from_files(con, "simples", sim_files)

    con.close()
    print("DuckDB criado e tabelas importadas em:", DB_PATH)


if __name__ == "__main__":
    main()
