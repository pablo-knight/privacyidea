"""Added token container template table and a 'template' column in the token container table.

Revision ID: c128c01a5520
Revises: 69e7817b9863
Create Date: 2024-09-12 09:33:18.656723

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.exc import OperationalError, ProgrammingError

# revision identifiers, used by Alembic.
revision = 'c128c01a5520'
down_revision = '69e7817b9863'


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    try:
        op.create_table('tokencontainertemplate',
                        sa.Column('id', sa.Integer(), sa.Identity(always=False), nullable=False),
                        sa.Column('options', sa.Unicode(length=2000), nullable=True),
                        sa.Column('name', sa.Unicode(length=200), nullable=True),
                        sa.Column('container_type', sa.Unicode(length=100), nullable=False),
                        sa.Column('default', sa.Boolean(), nullable=False),
                        sa.PrimaryKeyConstraint('id'),
                        mysql_row_format='DYNAMIC'
                        )
        op.add_column('tokencontainer', sa.Column('template_id', sa.Integer(), nullable=True))
    except (OperationalError, ProgrammingError) as exx:
        if "already exists" in str(exx.orig).lower():
            print("Table 'tokencontainertemplate' already exists.")
        else:
            print("Could not add table 'tokencontainertemplate' to database.")
            print(exx)
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_table('tokencontainertemplate')
    op.drop_column('tokencontainer', 'template_id')
    # ### end Alembic commands ###
