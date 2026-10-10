"""
Adapters for external providers, one subpackage per provider family.
Planned layout (PRD Ch.12 sec 26, 28, 31):

    integrations/payments/base.py        -> PaymentProvider interface
    integrations/payments/anchor.py      -> AnchorPaymentProvider
    integrations/payments/paystack.py    -> PaystackPaymentProvider
    integrations/media/cloudinary.py     -> signed upload authorization
    integrations/email/resend.py         -> transactional email client

Services depend on the abstract interfaces here, never on a specific
provider's SDK directly (PRD Ch.12 sec 28 "Payment Provider Abstraction").
"""
