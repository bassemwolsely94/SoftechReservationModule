"""
python manage.py seed_contract_terms

P-41: add a tracked ContractReceivableTerms row for every contract account in our sales history (channel 10, last
year) that has none — names read from SOFTECH (SELECT-only), insurance co-pay accounts grouped by company. Existing
rows (and their agreed days) are never changed. Finance then enters the agreed days on /finance/receivables.
"""
from django.core.management.base import BaseCommand

from apps.finance.receivables import seed_terms


class Command(BaseCommand):
    help = 'P-41: register the contract accounts to track as receivables.'

    def handle(self, *args, **o):
        n = seed_terms()
        self.stdout.write(self.style.SUCCESS(f'{n} contract account(s) added.'))
