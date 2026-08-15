# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
from datetime import date
import logging

_logger = logging.getLogger(__name__)


class PartnerPaymentInstallment(models.Model):
    _name = 'partner.payment.installment'
    _description = 'Payment Installment Line'
    _inherit = ['mail.thread']
    _order = 'plan_id, due_date, sequence'

    plan_id = fields.Many2one(
        'partner.payment.profile', string='Payment Plan', ondelete='cascade', index=True,
    )
    contract_id = fields.Many2one(
        'partner.contract', string='Contract', ondelete='cascade', index=True,
    )
    partner_id = fields.Many2one(
        'res.partner', string='Client', store=True, index=True,
        compute='_compute_partner_id',
    )
    sequence = fields.Integer(string='#', default=10)
    name = fields.Char(string='Label', compute='_compute_name', store=True)

    due_date = fields.Date(string='Due Date', required=True, tracking=True)
    amount_expected = fields.Monetary(string='Expected Amount', required=True, currency_field='currency_id')
    amount_paid = fields.Monetary(string='Amount Paid', default=0.0, currency_field='currency_id', tracking=True)
    amount_remaining = fields.Monetary(
        string='Remaining', compute='_compute_remaining', store=True, currency_field='currency_id',
    )
    currency_id = fields.Many2one(
        'res.currency', string='Currency',
        compute='_compute_currency_id', store=True,
    )

    state = fields.Selection([
        ('pending', 'Pending'), ('partial', 'Partial'), ('paid', 'Paid'),
        ('overdue', 'Overdue'), ('waived', 'Waived'),
    ], string='Status', default='pending', tracking=True)

    is_overdue = fields.Boolean(string='Is Overdue', compute='_compute_is_overdue', store=True)
    days_overdue = fields.Integer(string='Days Overdue', compute='_compute_is_overdue', store=True)

    invoice_id = fields.Many2one('account.move', string='Invoice', tracking=True)
    invoice_id_domain = fields.Char(compute='_compute_invoice_id_domain')

    @api.depends('plan_id', 'contract_id')
    def _compute_partner_id(self):
        for line in self:
            if line.plan_id:
                line.partner_id = line.plan_id.partner_id
            elif line.contract_id:
                line.partner_id = line.contract_id.partner_id
            else:
                line.partner_id = False

    @api.depends('plan_id.currency_id', 'contract_id.currency_id')
    def _compute_currency_id(self):
        company_currency = self.env.company.currency_id
        for line in self:
            if line.plan_id:
                line.currency_id = line.plan_id.currency_id
            elif line.contract_id:
                line.currency_id = line.contract_id.currency_id
            else:
                line.currency_id = company_currency

    @api.depends('partner_id')
    def _compute_invoice_id_domain(self):
        for line in self:
            if line.partner_id:
                line.invoice_id_domain = str([
                    ('partner_id', '=', line.partner_id.id),
                    ('move_type', 'in', ['out_invoice', 'out_refund']),
                    ('state', '=', 'posted'),
                ])
            else:
                line.invoice_id_domain = str([
                    ('move_type', 'in', ['out_invoice', 'out_refund']), ('state', '=', 'posted'),
                ])

    invoice_amount_total = fields.Monetary(
        related='invoice_id.amount_total', string='Invoice Total', currency_field='currency_id', readonly=True,
    )
    invoice_payment_state = fields.Selection(
        related='invoice_id.payment_state', string='Invoice Payment State', readonly=True,
    )
    invoice_date = fields.Date(related='invoice_id.invoice_date', string='Invoice Date', readonly=True, store=True)

    bank_id = fields.Many2one('res.partner.bank', string='Bank Account',
        domain="[('partner_id', '=', partner_id)]")

    payment_date = fields.Date(string='Payment Received Date', tracking=True)
    payment_reference = fields.Char(string='Payment Reference')
    payment_method = fields.Selection([
        ('cash', 'Cash'), ('cheque', 'Cheque'), ('transfer', 'Bank Transfer'),
        ('card', 'Card'), ('other', 'Other'),
    ], string='Payment Method')
    notes = fields.Char(string='Notes')

    @api.depends('sequence', 'plan_id', 'contract_id')
    def _compute_name(self):
        for line in self:
            line.name = _('Installment %d') % line.sequence

    @api.depends('amount_expected', 'amount_paid')
    def _compute_remaining(self):
        for line in self:
            line.amount_remaining = max(0.0, line.amount_expected - line.amount_paid)

    @api.depends('due_date', 'state')
    def _compute_is_overdue(self):
        today = date.today()
        for line in self:
            if line.state in ('paid', 'waived'):
                line.is_overdue = False
                line.days_overdue = 0
            elif line.due_date and line.due_date < today:
                line.is_overdue = True
                line.days_overdue = (today - line.due_date).days
            else:
                line.is_overdue = False
                line.days_overdue = 0

    @api.onchange('invoice_id')
    def _onchange_invoice_id(self):
        if self.invoice_id and not self.amount_expected:
            self.amount_expected = self.invoice_id.amount_residual or self.invoice_id.amount_total

    @api.onchange('amount_paid')
    def _onchange_amount_paid(self):
        self._auto_update_state()

    def action_mark_paid(self):
        for line in self:
            line.write({'amount_paid': line.amount_expected, 'state': 'paid', 'payment_date': fields.Date.today()})
            line._dismiss_overdue_activity()
        self._recompute_plan_amounts()

    def action_mark_waived(self):
        for line in self:
            line.write({'state': 'waived'})
            line._dismiss_overdue_activity()
        self._recompute_plan_amounts()

    def action_reset_pending(self):
        for line in self:
            if line.state == 'paid':
                raise ValidationError(_('Cannot reset a paid installment.'))
            line.write({'state': 'pending', 'amount_paid': 0.0})

    def _recompute_plan_amounts(self):
        self.mapped('plan_id')._compute_amounts()

    def _auto_update_state(self):
        today = date.today()
        for line in self:
            if line.amount_paid <= 0:
                line.state = 'overdue' if (line.due_date and line.due_date < today) else 'pending'
            elif line.amount_paid >= line.amount_expected:
                line.state = 'paid'
            else:
                line.state = 'partial'

    def _get_overdue_activity_type(self):
        return self.env.ref('mail.mail_activity_data_todo', raise_if_not_found=False)

    def _schedule_overdue_activity(self):
        activity_type = self._get_overdue_activity_type()
        if not activity_type:
            return
        for line in self:
            if not line.plan_id:
                continue
            existing = self.env['mail.activity'].search([
                ('res_model', '=', 'partner.payment.profile'),
                ('res_id', '=', line.plan_id.id),
                ('note', 'like', line.name),
                ('activity_type_id', '=', activity_type.id),
            ], limit=1)
            if existing:
                continue
            line.plan_id.activity_schedule(
                'mail.mail_activity_data_todo',
                date_deadline=fields.Date.today(),
                summary=_('Overdue installment: %s') % line.name,
                note=_(
                    'Installment <b>%(name)s</b> for client <b>%(partner)s</b> '
                    'was due on <b>%(due)s</b> — %(days)d day(s) overdue.<br/>'
                    'Expected: %(expected)s | Paid: %(paid)s | Remaining: %(rem)s'
                ) % {'name': line.name, 'partner': line.partner_id.name, 'due': line.due_date,
                     'days': line.days_overdue, 'expected': line.amount_expected,
                     'paid': line.amount_paid, 'rem': line.amount_remaining},
            )

    def _dismiss_overdue_activity(self):
        activity_type = self._get_overdue_activity_type()
        if not activity_type:
            return
        for line in self:
            if not line.plan_id:
                continue
            activities = self.env['mail.activity'].search([
                ('res_model', '=', 'partner.payment.profile'),
                ('res_id', '=', line.plan_id.id),
                ('note', 'like', line.name),
                ('activity_type_id', '=', activity_type.id),
            ])
            activities.action_done()

    @api.model
    def _cron_update_overdue_states(self):
        today = date.today()
        _logger.info('Running payment installment overdue check for %s', today)
        newly_overdue = self.search([
            ('state', 'in', ('pending', 'partial')),
            ('due_date', '<', fields.Date.to_string(today)),
        ])
        if newly_overdue:
            _logger.info('Marking %d installment(s) as overdue', len(newly_overdue))
            newly_overdue.write({'state': 'overdue'})
            newly_overdue._compute_is_overdue()
            newly_overdue._schedule_overdue_activity()
            newly_overdue._recompute_plan_amounts()
        existing_overdue = self.search([('state', '=', 'overdue')])
        if existing_overdue:
            existing_overdue._compute_is_overdue()
        _logger.info('Payment installment overdue check complete')

    @api.constrains('amount_paid')
    def _check_amount_paid(self):
        for line in self:
            if line.amount_paid < 0:
                raise ValidationError(_('Amount paid cannot be negative.'))
