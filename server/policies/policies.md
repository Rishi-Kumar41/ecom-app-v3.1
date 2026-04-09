# ECOM-APP Policies (Support + Customer)

## Scope
These policies apply to the ECOM-APP web store and customer support operations.

---

## 1) Ordering & Payment
### Supported payment methods
- Online payment (Stripe) — CURRENT
- Cash on Delivery (COD) — PLANNED

### Order status basics (simplified)
- PENDING_PAYMENT: order created, payment not completed
- PAID: payment completed successfully

---

## 2) Cancellation Policy

### CURRENT (what the system enforces today)
- Cancellation is allowed only while the order is in **PENDING_PAYMENT** status.
- Once payment succeeds (PAID), cancellation is not available through the current UI/API.

### PLANNED (future behavior — to be enabled with tool calling + COD)
- Cancellation may be allowed within **7 days** of order placement for eligible orders.
- Some items may be non-cancellable after dispatch.
- Quantity limits and fraud checks may apply.

---

## 3) Returns / Refunds Policy (PLANNED)
> Returns are not fully implemented in the current system, but the policy is defined for future enablement.

### Eligibility
- Return request within **7 days** of delivery (recommended policy) OR within **7 days** of order placement (alternate policy).
- Items must be in reasonable condition; accessories and original packaging preferred.
- Certain categories may be non-returnable depending on product type.

### Quantity limits
- Maximum **2 units per product per order** eligible for return processing via the support flow.

### Refund method
- For prepaid orders: refund to the original payment method (Stripe).
- For COD orders: refund to a supported method (UPI/bank transfer) — PLANNED.

---

## 4) Exchange Policy (PLANNED)
- Exchanges are treated as a return + replacement order.
- Eligibility follows the same conditions as Returns.

---

## 5) Support (Admin) Workflow Rules — ASM-style (PLANNED)
This is the intended support agent workflow:
1. Admin logs in to Support.
2. Admin selects the customer to assist.
3. Admin can create/cancel/return orders on behalf of the customer.
4. Admin actions are logged for auditing.

---

## 6) Answering Rules for the Assistant (RAG)
When answering questions:
- Answer only using the policy content and the product/order information provided in context.
- If a policy is "PLANNED", clearly state that it is planned and not yet enforced by the system.
- Do not guess or invent policy rules not present in this document.