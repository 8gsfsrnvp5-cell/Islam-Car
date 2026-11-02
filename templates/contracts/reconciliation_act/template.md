# АКТ СВЕРКИ РАСЧЁТОВ

> по договору купли-продажи автомобиля № {{ contract.number }} от {{ contract.signed_at }} · по состоянию на {{ ledger.as_of }}

Продавец: {{ seller.name }}. Покупатель: {{ client.full_name }}. Автомобиль: {{ car.title }}, VIN {{ car.vin }}.

Цена автомобиля по договору — {{ contract.sale_price_words }}.

## Поступившие платежи

::payments::

## Исполнение графика

::ledger::

Итого оплачено {{ ledger.paid_words }}. Остаток задолженности — {{ ledger.outstanding_words }}{% if ledger.has_overdue %}, в том числе просрочено {{ ledger.overdue_words }}{% endif %}. Проценты и неустойка не начислялись.

::signatures:seller,buyer::
