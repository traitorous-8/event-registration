"""schema hardening constraints and server defaults

Revision ID: 07fbb1c5f2d2
Revises: e0151147879b
Create Date: 2026-10-30 12:35:50.532071

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '07fbb1c5f2d2'
down_revision: Union[str, None] = 'e0151147879b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # server_default = now() for created_at and queued_at
    op.alter_column('events', 'created_at', server_default=sa.text('now()'))
    op.alter_column('registrations', 'created_at', server_default=sa.text('now()'))
    op.alter_column('registrations', 'queued_at', server_default=sa.text('now()'))
    op.alter_column('notifications', 'created_at', server_default=sa.text('now()'))

    # check constraints
    op.create_check_constraint(
        'check_registration_status_valid',
        'registrations',
        "status IN ('confirmed', 'waitlist', 'cancelled')"
    )
    op.create_check_constraint(
        'check_registration_email_lowercased',
        'registrations',
        "email = lower(email)"
    )
    op.create_check_constraint(
        'check_notification_status_valid',
        'notifications',
        "status IN ('pending', 'sent', 'failed')"
    )


def downgrade() -> None:
    op.drop_constraint('check_notification_status_valid', 'notifications', type_='check')
    op.drop_constraint('check_registration_email_lowercased', 'registrations', type_='check')
    op.drop_constraint('check_registration_status_valid', 'registrations', type_='check')

    op.alter_column('notifications', 'created_at', server_default=None)
    op.alter_column('registrations', 'queued_at', server_default=None)
    op.alter_column('registrations', 'created_at', server_default=None)
    op.alter_column('events', 'created_at', server_default=None)
