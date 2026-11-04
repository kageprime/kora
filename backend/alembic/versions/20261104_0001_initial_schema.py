"""Initial Kora schema: scholars, works, provenance, links and review queue.

Revision ID: 0001_initial
Revises:
Create Date: 2026-11-04
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "scholars",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("scholar_key", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=500), nullable=False),
        sa.Column("name_key", sa.String(length=500), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("birth_year", sa.Integer(), nullable=True),
        sa.Column("death_year", sa.Integer(), nullable=True),
        sa.Column("wikipedia_title", sa.String(length=500), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_scholars_scholar_key",
        "scholars",
        ["scholar_key"],
        unique=True,
    )
    op.create_index("ix_scholars_name_key", "scholars", ["name_key"])

    op.create_table(
        "works",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("work_key", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=1000), nullable=False),
        sa.Column("title_key", sa.String(length=1000), nullable=False),
        sa.Column("category", sa.String(length=20), nullable=False),
        sa.Column("year", sa.Integer(), nullable=True),
        sa.Column("venue", sa.String(length=1000), nullable=True),
        sa.Column("cover_url", sa.Text(), nullable=True),
        sa.Column("cited_by", sa.Integer(), nullable=False),
        sa.Column("edition_count", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_works_work_key", "works", ["work_key"], unique=True)
    op.create_index("ix_works_title_key", "works", ["title_key"])

    op.create_table(
        "identities",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("scholar_id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("source_id", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=500), nullable=False),
        sa.Column("alt_names", sa.JSON(), nullable=False),
        sa.Column("confidence", sa.String(length=20), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("birth_year", sa.Integer(), nullable=True),
        sa.Column("death_year", sa.Integer(), nullable=True),
        sa.Column("works_count", sa.Integer(), nullable=True),
        sa.Column("affiliations", sa.JSON(), nullable=False),
        sa.Column("identifiers", sa.JSON(), nullable=False),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("popularity", sa.Integer(), nullable=False),
        sa.Column("wikipedia_title", sa.String(length=500), nullable=True),
        sa.ForeignKeyConstraint(
            ["scholar_id"],
            ["scholars.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "source", "source_id", name="uq_identity_source"
        ),
    )
    op.create_index("ix_identities_scholar_id", "identities", ["scholar_id"])

    op.create_table(
        "work_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("work_id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("source_id", sa.String(length=255), nullable=False),
        sa.Column("title", sa.String(length=1000), nullable=False),
        sa.Column("category", sa.String(length=20), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("year", sa.Integer(), nullable=True),
        sa.Column("authors", sa.JSON(), nullable=False),
        sa.Column("venue", sa.String(length=1000), nullable=True),
        sa.Column("doi", sa.String(length=255), nullable=True),
        sa.Column("isbns", sa.JSON(), nullable=False),
        sa.Column("languages", sa.JSON(), nullable=False),
        sa.Column("cover_url", sa.Text(), nullable=True),
        sa.Column("cited_by", sa.Integer(), nullable=True),
        sa.Column("edition_count", sa.Integer(), nullable=True),
        sa.Column("links", sa.JSON(), nullable=False),
        sa.Column("raw_type", sa.String(length=100), nullable=True),
        sa.ForeignKeyConstraint(
            ["work_id"],
            ["works.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "work_id", "source", "source_id", name="uq_work_record_source"
        ),
    )
    op.create_index("ix_work_records_work_id", "work_records", ["work_id"])
    op.create_index("ix_work_records_doi", "work_records", ["doi"])

    op.create_table(
        "work_links",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("work_id", sa.Integer(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.Column("label", sa.String(length=255), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["work_id"],
            ["works.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("work_id", "url", name="uq_work_link_url"),
    )
    op.create_index("ix_work_links_work_id", "work_links", ["work_id"])

    op.create_table(
        "scholar_works",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("scholar_id", sa.Integer(), nullable=False),
        sa.Column("work_id", sa.Integer(), nullable=False),
        sa.Column("relation", sa.String(length=20), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.ForeignKeyConstraint(
            ["scholar_id"],
            ["scholars.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["work_id"],
            ["works.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "scholar_id", "work_id", name="uq_scholar_work"
        ),
    )
    op.create_index(
        "ix_scholar_works_scholar_id", "scholar_works", ["scholar_id"]
    )
    op.create_index("ix_scholar_works_work_id", "scholar_works", ["work_id"])

    op.create_table(
        "scholar_profiles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("scholar_id", sa.Integer(), nullable=False),
        sa.Column("query", sa.String(length=500), nullable=False),
        sa.Column("bio", sa.Text(), nullable=True),
        sa.Column("bio_url", sa.Text(), nullable=True),
        sa.Column("source_status", sa.JSON(), nullable=False),
        sa.Column("raw_work_count", sa.Integer(), nullable=False),
        sa.Column("alternatives", sa.JSON(), nullable=False),
        sa.Column("flagged", sa.JSON(), nullable=False),
        sa.Column(
            "refreshed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("last_attempted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("refresh_error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["scholar_id"],
            ["scholars.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("scholar_id", name="uq_scholar_profile"),
    )
    op.create_index(
        "ix_scholar_profiles_scholar_id", "scholar_profiles", ["scholar_id"]
    )

    op.create_table(
        "review_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("scholar_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=1000), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["scholar_id"],
            ["scholars.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "scholar_id", "kind", "fingerprint", name="uq_review_item"
        ),
    )
    op.create_index("ix_review_items_scholar_id", "review_items", ["scholar_id"])
    op.create_index(
        "ix_review_items_status_kind", "review_items", ["status", "kind"]
    )


def downgrade() -> None:
    op.drop_index("ix_review_items_status_kind", table_name="review_items")
    op.drop_index("ix_review_items_scholar_id", table_name="review_items")
    op.drop_table("review_items")

    op.drop_index(
        "ix_scholar_profiles_scholar_id", table_name="scholar_profiles"
    )
    op.drop_table("scholar_profiles")

    op.drop_index("ix_scholar_works_work_id", table_name="scholar_works")
    op.drop_index("ix_scholar_works_scholar_id", table_name="scholar_works")
    op.drop_table("scholar_works")

    op.drop_index("ix_work_links_work_id", table_name="work_links")
    op.drop_table("work_links")

    op.drop_index("ix_work_records_doi", table_name="work_records")
    op.drop_index("ix_work_records_work_id", table_name="work_records")
    op.drop_table("work_records")

    op.drop_index("ix_identities_scholar_id", table_name="identities")
    op.drop_table("identities")

    op.drop_index("ix_works_title_key", table_name="works")
    op.drop_index("ix_works_work_key", table_name="works")
    op.drop_table("works")

    op.drop_index("ix_scholars_name_key", table_name="scholars")
    op.drop_index("ix_scholars_scholar_key", table_name="scholars")
    op.drop_table("scholars")
