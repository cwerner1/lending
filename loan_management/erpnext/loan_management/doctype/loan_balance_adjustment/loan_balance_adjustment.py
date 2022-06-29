# Copyright (c) 2022, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
import erpnext
from frappe import _
from frappe.utils import nowdate, add_days
from erpnext.controllers.accounts_controller import AccountsController
from erpnext.loan_management.doctype.process_loan_interest_accrual.process_loan_interest_accrual import (
    process_loan_interest_accrual_for_demand_loans,
)
from erpnext.accounts.general_ledger import make_gl_entries


class LoanBalanceAdjustment(AccountsController):
    """
    Add credit/debit adjustments to loan ledger.
    """

    def validate(self):
        if self.amount == 0:
            frappe.throw(_("Amount cannot be zero"))
        if self.amount < 0:
            frappe.throw(_("Amount cannot be negative"))
        self.set_missing_values()

    def on_submit(self):
        self.set_status_and_amounts()
        self.make_gl_entries()

    def on_cancel(self):
        self.set_status_and_amounts(cancel=1)
        self.make_gl_entries(cancel=1)
        self.ignore_linked_doctypes = ["GL Entry", "Payment Ledger Entry"]

    def set_missing_values(self):
        if not self.posting_date:
            self.posting_date = nowdate()

        if not self.cost_center:
            self.cost_center = erpnext.get_default_cost_center(self.company)

    def set_status_and_amounts(self, cancel=0):
        loan_details = frappe.get_all(
            "Loan",
            fields=[
                "loan_amount",
                "adjustment_amount",
                "total_payment",
                "total_principal_paid",
                "total_interest_payable",
                "status",
                "is_term_loan",
                "is_secured_loan",
            ],
            filters={"name": self.loan},
        )[0]

        if cancel:
            adjustment_amount = self.get_values_on_cancel(loan_details)
        else:
            adjustment_amount = self.get_values_on_submit(loan_details)

        frappe.db.set_value(
            "Loan",
            self.loan,
            {
                "adjustment_amount": adjustment_amount,
            },
        )

    def get_values_on_cancel(self, loan_details):
        if self.adjustment_type == "Credit Adjustment":
            adjustment_amount = loan_details.adjustment_amount - self.amount
        elif self.adjustment_type == "Debit Adjustment":
            adjustment_amount = loan_details.adjustment_amount + self.amount

        return adjustment_amount

    def get_values_on_submit(self, loan_details):
        if self.adjustment_type == "Credit Adjustment":
            adjustment_amount = loan_details.adjustment_amount + self.amount
        elif self.adjustment_type == "Debit Adjustment":
            adjustment_amount = loan_details.adjustment_amount - self.amount

        if (
            loan_details.status in ("Disbursed", "Partially Disbursed")
            and not loan_details.is_term_loan
        ):
            process_loan_interest_accrual_for_demand_loans(
                posting_date=add_days(self.posting_date, -1),
                loan=self.loan,
                accrual_type=self.adjustment_type,
            )

        return adjustment_amount

    def make_gl_entries(self, cancel=0, adv_adj=0):
        gle_map = []

        loan_entry = {
            "account": self.loan_account,
            "against": self.adjustment_account,
            "against_voucher_type": "Loan",
            "against_voucher": self.loan,
            "remarks": _("{} against loan:".format(self.adjustment_type)) + self.loan,
            "cost_center": self.cost_center,
            "party_type": self.applicant_type,
            "party": self.applicant,
            "posting_date": self.posting_date,
        }
        company_entry = {
            "account": self.adjustment_account,
            "against": self.loan_account,
            "against_voucher_type": "Loan",
            "against_voucher": self.loan,
            "remarks": _("{} against loan:".format(self.adjustment_type)) + self.loan,
            "cost_center": self.cost_center,
            "posting_date": self.posting_date,
        }
        if self.adjustment_type == "Credit Adjustment":
            loan_entry["credit"] = self.amount
            loan_entry["credit_in_account_currency"] = self.amount

            company_entry["debit"] = self.amount
            company_entry["debit_in_account_currency"] = self.amount

        elif self.adjustment_type == "Debit Adjustment":
            loan_entry["debit"] = self.amount
            loan_entry["debit_in_account_currency"] = self.amount

            company_entry["credit"] = self.amount
            company_entry["credit_in_account_currency"] = self.amount

        gle_map.append(self.get_gl_dict(loan_entry))

        gle_map.append(self.get_gl_dict(company_entry))

        if gle_map:
            make_gl_entries(gle_map, cancel=cancel, adv_adj=adv_adj, merge_entries=False)