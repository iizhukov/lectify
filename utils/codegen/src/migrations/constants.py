TYPE_NORMALIZE = {
    "INTEGER": "INTEGER", "INT": "INTEGER",
    "BIGINTEGER": "BIGINTEGER", "BIGINT": "BIGINTEGER",
    "SMALLINTEGER": "SMALLINTEGER", "SMALLINT": "SMALLINTEGER",
    "VARCHAR": "VARCHAR", "STRING": "VARCHAR",
    "CHAR": "CHAR", "TEXT": "TEXT",
    "BOOLEAN": "BOOLEAN", "BOOL": "BOOLEAN",
    "DATETIME": "DATETIME", "DATE": "DATE", "TIME": "TIME",
    "FLOAT": "FLOAT", "NUMERIC": "NUMERIC", "DECIMAL": "NUMERIC",
    "UUID": "UUID", "JSON": "JSON", "JSONB": "JSONB",
}

SA_TYPE_MAPPING = {
    "INTEGER": "Integer", "BIGINTEGER": "BigInteger", "SMALLINTEGER": "SmallInteger",
    "VARCHAR": "String", "CHAR": "String", "TEXT": "Text",
    "BOOLEAN": "Boolean", "DATETIME": "DateTime", "DATE": "Date", "TIME": "Time",
    "FLOAT": "Float", "NUMERIC": "Numeric", "UUID": "Uuid", "JSON": "JSON", "JSONB": "JSONB",
}

MIGRATIONS_TABLE = "_migrations"
REVISION_PATTERN = r"^(\d{4})_"
REVISION_FORMAT = "{:04d}"
