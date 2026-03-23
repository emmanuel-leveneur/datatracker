"""Helpers partagés entre les modules de tests."""
from app.models import DataTable, TableColumn, TableOwner, ColumnType


def make_table(db, owner, name="TestTable", columns=None):
    """Crée une DataTable avec ses colonnes, ajoute le créateur en propriétaire, et retourne (table, [cols])."""
    table = DataTable(name=name, created_by_id=owner.id)
    cols = []
    if columns:
        for i, (cname, ctype) in enumerate(columns):
            cols.append(TableColumn(name=cname, col_type=ctype, order=i))
    table.columns = cols
    db.add(table)
    db.flush()
    db.add(TableOwner(table_id=table.id, user_id=owner.id))
    db.commit()
    db.refresh(table)
    return table, cols
