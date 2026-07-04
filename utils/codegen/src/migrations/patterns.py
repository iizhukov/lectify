import re


class MigrationPatterns:
    DROP_TABLE = re.compile(r'op\.drop_table\(\s*[\'"]([\w]+)[\'"]\s*\)', re.DOTALL)
    DROP_COLUMN = re.compile(r'op\.drop_column\(\s*[\'"]([\w]+)[\'"],\s*[\'"]([\w]+)[\'"]\s*\)', re.DOTALL)
    CREATE_TABLE = re.compile(
        r'op\.create_table\(\s*[\'"]([\w]+)[\'"],\s*(.*?)(?=\n\s*(?:op\.\w+\(|\)\s*$))',
        re.DOTALL
    )
    ADD_COLUMN = re.compile(
        r'op\.add_column\(\s*[\'"]([\w]+)[\'"],\s*sa\.Column\(\s*[\'"]([\w]+)[\'"],\s*sa\.(\w+(?:\(\d+(?:,\d+)?\))?)'
    )
    ALTER_COLUMN = re.compile(r'op\.alter_column\(\s*[\'"]([\w]+)[\'"],\s*[\'"]([\w]+)[\'"]')
    REVISION_ID = re.compile(r"revision:\s*str\s*=\s*['\"](\w+)['\"]")
    DOWN_REVISION = re.compile(r"down_revision.*?=\s*['\"](\w+)['\"]")
    COLUMN_DEFINITION = re.compile(r'sa\.Column\(\s*[\'"]([\w]+)[\'"],\s*sa\.(\w+(?:\(\d+(?:,\d+)?\))?)')
    TYPE_WITH_PARAMS = re.compile(r"(\w+)\((\d+(?:,\d+)?)\)")
    MIGRATION_FILENAME = re.compile(r"^(\d{4})_(.+)$")
