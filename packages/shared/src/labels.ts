// Подписи статусов на русском — одинаковые в админке и на клиентском сайте.

export const AVAILABILITY: Record<string, string> = {
  in_stock: "В наличии",
  purchasing: "В процессе закупки",
  reserved: "Забронирован",
};

export const AVAILABILITY_HINT: Record<string, string> = {
  in_stock: "Автомобиль в собственности продавца и может быть передан после оформления договора.",
  purchasing: "Продавец ещё оформляет покупку. Договор можно заключить только после перехода права собственности.",
  reserved: "По автомобилю идёт оформление сделки с другим покупателем.",
};

export const CAR_STATUS: Record<string, string> = {
  draft: "Черновик",
  available: "В продаже",
  reserved: "Забронирован",
  sold: "Продан",
  archived: "В архиве",
};

export const OWNERSHIP: Record<string, string> = {
  owned: "В собственности",
  purchasing: "В процессе закупки",
};

export const APPLICATION_STATUS: Record<string, string> = {
  new: "Новая",
  in_progress: "В работе",
  info_requested: "Запрошены сведения",
  offer_made: "Предложены условия",
  converted: "Договор заключён",
  rejected: "Отказ",
  withdrawn: "Отозвана клиентом",
};

export const APPLICATION_KIND: Record<string, string> = {
  catalog: "Из каталога",
  custom_order: "Под заказ",
};

export const CONTRACT_STATUS: Record<string, string> = {
  draft: "Черновик",
  signed: "Действует",
  completed: "Исполнен",
  cancelled: "Отменён",
};

export const ROW_STATUS: Record<string, string> = {
  paid: "Оплачен",
  partial: "Оплачен частично",
  overdue: "Просрочен",
  due_today: "Срок сегодня",
  upcoming: "Предстоит",
};

export const PAYMENT_METHOD: Record<string, string> = {
  bank_transfer: "Банковский перевод",
  cash: "Наличные (касса)",
  card: "Банковская карта",
  other: "Другое",
};

export const PAYMENT_STATUS: Record<string, string> = {
  confirmed: "Учтён",
  reversed: "Сторнирован",
};

export const REPORT_STATUS: Record<string, string> = {
  pending: "На проверке",
  matched: "Подтверждён",
  rejected: "Не найден",
};

export const THREAD_TOPIC: Record<string, string> = {
  general: "Общий вопрос",
  payment_difficulty: "Сложности с платежом",
  schedule_change: "Изменение графика",
  early_repayment: "Досрочное погашение",
  documents: "Документы",
};

export const THREAD_STATUS: Record<string, string> = {
  open: "Ожидает ответа",
  answered: "Есть ответ",
  closed: "Закрыто",
};

export const PARTY_TYPE: Record<string, string> = {
  individual: "Физическое лицо",
  ip: "Индивидуальный предприниматель",
  llc: "ООО",
};

export const SELLER_REGIME: Record<string, string> = {
  individual_one_off: "Физлицо — разовая продажа личного имущества",
  ip: "Индивидуальный предприниматель",
  llc: "ООО",
};

export const ROLE: Record<string, string> = {
  owner: "Владелец",
  admin: "Администратор",
  manager: "Менеджер",
  accountant: "Бухгалтер",
  client: "Покупатель",
};

export function label(map: Record<string, string>, key: string | null | undefined): string {
  if (!key) return "—";
  return map[key] ?? key;
}

export const DOC_STATUS: Record<string, string> = {
  draft: "Черновик",
  pending_approval: "На утверждении",
  approved: "Утверждён",
  signed: "Подписан",
  cancelled: "Отменён",
};

export const MESSAGE_STATUS: Record<string, string> = {
  scheduled: "Запланировано",
  sent: "Отправлено",
  failed: "Не доставлено",
  cancelled: "Отменено",
  skipped: "Не отправлялось",
};

export const CHANNEL: Record<string, string> = {
  internal: "Личный кабинет",
  sms: "SMS",
  email: "E-mail",
};

export const NOTIFY_EVENT: Record<string, string> = {
  before_due: "До платежа",
  due_day: "В день платежа",
  overdue: "После просрочки",
  payment_confirmed: "После подтверждения оплаты",
};

export const PLEDGE_STATUS: Record<string, string> = {
  planned: "Планируется",
  documents_prepared: "Документы подготовлены",
  submitted: "Передано нотариусу",
  registered: "Зарегистрирован",
  release_required: "Нужно прекратить",
  release_submitted: "Прекращение подано",
  released: "Прекращён",
  not_required: "Не требуется",
};

export const INSURANCE_KIND: Record<string, string> = {
  osago: "ОСАГО",
  kasko: "КАСКО",
  other: "Другое",
};

export const TASK_STATUS: Record<string, string> = {
  open: "Открыта",
  done: "Выполнена",
  cancelled: "Отменена",
};
