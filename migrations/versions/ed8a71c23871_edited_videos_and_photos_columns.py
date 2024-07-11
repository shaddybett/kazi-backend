"""edited videos and photos columns

Revision ID: ed8a71c23871
Revises: 197cc1011d81
Create Date: 2024-07-11 11:14:53.316634

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'ed8a71c23871'
down_revision = '197cc1011d81'
branch_labels = None
depends_on = None



def upgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.alter_column(
            'image',
            type_=sa.LargeBinary(),
            existing_type=sa.String(),
            postgresql_using='image::bytea',
            nullable=True
        )
        batch_op.add_column(sa.Column('image_filename', sa.String(length=255), nullable=True))

def downgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('image_filename')
        batch_op.alter_column(
            'image',
            type_=sa.String(),
            existing_type=sa.LargeBinary(),
            nullable=True
        )

    # ### end Alembic commands ###
