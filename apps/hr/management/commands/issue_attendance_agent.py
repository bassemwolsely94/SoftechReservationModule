"""
Create an attendance agent and print its secret once. Only the hash is stored, so a lost secret
means issuing a new agent. The secret is the last line of the output.
"""
from django.core.management.base import BaseCommand

from apps.audit.models import AuditLog
from apps.hr.attendance.agent_auth import issue_agent


class Command(BaseCommand):
    help = 'Create an attendance agent and print its secret once.'

    def add_arguments(self, parser):
        parser.add_argument('name')

    def handle(self, *args, **opts):
        agent, secret = issue_agent(opts['name'])
        AuditLog.log('hr_attendance_agent_issue', obj=agent, note='Agent secret issued from the command line')
        self.stdout.write(f'Agent {agent.pk} created. Copy this secret now; it is not shown again:')
        self.stdout.write(secret)
