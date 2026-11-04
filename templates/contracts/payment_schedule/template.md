# ГРАФИК ПЛАТЕЖЕЙ

> Приложение № 1 к договору купли-продажи автомобиля № {{ contract.number }} от {{ contract.signed_at }}

Автомобиль: {{ car.title }}, VIN {{ car.vin }}. Цена Автомобиля — {{ contract.sale_price_words }}. Цена окончательная.

::schedule::

Платёж считается внесённым с момента зачисления денежных средств на счёт Продавца: получатель {{ seller.bank_payee or seller.name }}, банк {{ seller.bank_name }}, БИК {{ seller.bank_bik }}, р/с {{ seller.bank_account }}{% if seller.bank_corr_account %}, к/с {{ seller.bank_corr_account }}{% endif %}. Назначение платежа: «Оплата по договору № {{ contract.number }}». Проценты и неустойка за нарушение сроков не начисляются.

::signatures:seller,buyer::
