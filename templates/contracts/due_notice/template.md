# УВЕДОМЛЕНИЕ О ПРИБЛИЖЕНИИ СРОКА ОПЛАТЫ

> {{ today }}

Уважаемый(ая) {{ client.full_name }}!

{{ seller.name }} напоминает, что по договору купли-продажи автомобиля № {{ contract.number }} от {{ contract.signed_at }} ближайший платёж по графику — {{ ledger.next_due_words }}, срок оплаты — {{ ledger.next_due_date }}.

Реквизиты для оплаты: получатель {{ seller.bank_payee or seller.name }}, банк {{ seller.bank_name }}, БИК {{ seller.bank_bik }}, р/с {{ seller.bank_account }}{% if seller.bank_corr_account %}, к/с {{ seller.bank_corr_account }}{% endif %}. Назначение платежа: «Оплата по договору № {{ contract.number }}».

Если платёж уже внесён, пожалуйста, не учитывайте это уведомление. Информация о платежах доступна в личном кабинете.

::signatures:seller::
