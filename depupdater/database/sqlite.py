"""SQLite operations with explicit errors and scoped connection/transaction lifetime."""
from pathlib import Path
import sqlite3


class Sqlite:
    def __init__(self, sqlite_path, *, must_exist=False, timeout=30):
        self.sqlite_path = sqlite_path
        self.must_exist = must_exist
        self.timeout = timeout
        self.conn = None
        self.cursor = None
        self._in_context = False

    def connect(self):
        if self.conn is not None:
            return self
        target = self.sqlite_path
        if self.must_exist:
            # Do not silently create an empty database when a snapshot is missing.
            target = Path(target).resolve().as_uri() + '?mode=rw'
        self.conn = sqlite3.connect(target, timeout=self.timeout, uri=self.must_exist)
        self.cursor = self.conn.cursor()
        return self

    def __enter__(self):
        self.connect()
        self._in_context = True
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            if exc_type is None:
                self.conn.commit()
            else:
                self.conn.rollback()
        finally:
            self.close()

    def close(self):
        try:
            if self.cursor is not None:
                self.cursor.close()
        finally:
            if self.conn is not None:
                self.conn.close()
            self.cursor = None
            self.conn = None
            self._in_context = False

    @staticmethod
    def _conditions(conditions):
        fragments, values = [], []
        for condition in conditions:
            if isinstance(condition, str):
                fragments.append(condition)
            else:
                column, operator, value = condition
                fragments.append(f'{column} {operator} ?')
                values.append(value)
        return ' '.join(fragments), values

    def _write(self, sql, values=()):
        try:
            self.cursor.execute(sql, values)
            # A scoped operation can combine multiple writes atomically. Preserve
            # immediate commits for callers still using connect()/close().
            if not self._in_context:
                self.conn.commit()
        except sqlite3.Error:
            if not self._in_context:
                self.conn.rollback()
            raise

    def create_table(self, table_name, columns):
        definitions = ', '.join(f'{name} {kind}' for name, kind in columns.items())
        self._write(f'CREATE TABLE IF NOT EXISTS {table_name} ({definitions})')

    def insert_data(self, table_name, data):
        columns = ', '.join(data)
        placeholders = ', '.join('?' for _ in data)
        self._write(f'INSERT OR IGNORE INTO {table_name} ({columns}) VALUES ({placeholders})', list(data.values()))

    def query_data(self, table_name, columns='*', conditions=None):
        sql = f'SELECT {columns} FROM {table_name}'
        values = []
        if conditions:
            clause, values = self._conditions(conditions)
            sql += f' WHERE {clause}'
        self.cursor.execute(sql, values)
        return self.cursor.fetchall()

    def update_data(self, table_name, updates, conditions):
        assignments = ', '.join(f'{column}=?' for column in updates)
        clause, values = self._conditions(conditions)
        self._write(f'UPDATE {table_name} SET {assignments} WHERE {clause}', list(updates.values()) + values)

    def delete_data(self, table_name, conditions):
        clause, values = self._conditions(conditions)
        self._write(f'DELETE FROM {table_name} WHERE {clause}', values)

    def drop_table(self, table_name):
        self._write(f'DROP TABLE IF EXISTS {table_name}')

    def create_index(self, table_name, index_name, columns):
        if isinstance(columns, str):
            columns = [columns]
        self._write(f'CREATE INDEX IF NOT EXISTS {index_name} ON {table_name} ({", ".join(columns)})')
