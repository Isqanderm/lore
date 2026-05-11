# Add Migration

Use when writing an Alembic migration for Lore — schema changes, new indexes, column additions.

**Announce at start:** "Using add-migration to create migration for [what changes]."

---

## Rules for Lore migrations

1. **Never use PostgreSQL ENUM** for SourceType-like fields — use `TEXT` always
2. **Never DROP tables in upgrade()** — use `downgrade()` for reversibility
3. **HNSW index for Vector(3072)** — do NOT add yet (needs pgvector ≥0.8.0). Add GIN for tsvector instead.
4. **Always include `CREATE EXTENSION IF NOT EXISTS vector`** in the first migration, not in subsequent ones
5. **Migration files are append-only** — never edit an existing migration that has been applied

---

## Step-by-step

### Step 1 — Generate the file

```bash
make migration name=<descriptive_name>
```

File appears in `migrations/versions/<hash>_<descriptive_name>.py`.

### Step 2 — Write upgrade()

```python
def upgrade() -> None:
    # New table example
    op.create_table(
        "<table_name>",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_<table>_<field>", "<table>", ["<field>"])

    # Add column example
    op.add_column("<table>", sa.Column("<column>", sa.Text(), nullable=True))

    # Add index example
    op.create_index(
        "ix_<table>_<field>",
        "<table>",
        ["<field>"],
        postgresql_using="gin",  # for tsvector fields
    )
```

### Step 3 — Write downgrade()

Must exactly reverse upgrade():
```python
def downgrade() -> None:
    op.drop_index("ix_<table>_<field>", table_name="<table>")
    op.drop_table("<table>")
    # for add_column:
    # op.drop_column("<table>", "<column>")
```

### Step 4 — Test the migration

```bash
# Apply
make migrate

# Verify alembic history
uv run alembic history

# Test downgrade works
uv run alembic downgrade -1
uv run alembic upgrade head
```

### Step 5 — Run integration tests

Integration tests use `Base.metadata.create_all` (not alembic), so they pick up ORM changes automatically. But verify nothing broke:

```bash
make test-integration
make test-e2e
```

### Step 6 — Commit

```bash
git add migrations/versions/<file>.py
git commit -m "feat: migration — <what changed>"
```

---

## Column type reference

| Need | SQLAlchemy type |
|---|---|
| UUID primary key | `sa.UUID()` |
| Short text / enum-like | `sa.Text()` |
| Long content | `sa.Text()` |
| Integer version | `sa.Integer()` |
| Timestamp with tz | `sa.DateTime(timezone=True)` |
| JSON blob | `postgresql.JSONB()` |
| pgvector 3072-dim | `Vector(3072)` from `pgvector.sqlalchemy` |
| Computed tsvector | `sa.Computed("to_tsvector('english', text)", persisted=True)` |

## Index type reference

| Use case | `postgresql_using` |
|---|---|
| Full-text search (tsvector) | `"gin"` |
| Vector ANN search (future) | `"hnsw"` — defer, needs pgvector ≥0.8.0 |
| Standard B-tree | omit (default) |
