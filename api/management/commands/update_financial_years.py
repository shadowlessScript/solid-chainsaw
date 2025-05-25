from django.core.management.base import BaseCommand
from api.models import BudgetFinancialYear  

class Command(BaseCommand):
    help = 'Recalculate and update financials for all BudgetFinancialYear records.'

    def handle(self, *args, **kwargs):
        # Fetch all financial year records
        financial_years = BudgetFinancialYear.objects.all()

        # Loop through and update each one
        for fy in financial_years:
            fy.update_financials()  # This is the method defined in your model
            self.stdout.write(f"Updated: {fy.Year}")

        self.stdout.write(self.style.SUCCESS('Successfully updated all BudgetFinancialYear records.'))
