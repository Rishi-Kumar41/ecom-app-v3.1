// client/src/pages/orders/orders.component.ts
import { Component, OnInit } from "@angular/core";
import { CommonModule } from "@angular/common";
import { OrdersService, OrderOut } from "../../services/orders.service";
import { RouterLink } from "@angular/router";

@Component({
  standalone: true,
  selector: "app-orders",
  imports: [CommonModule, RouterLink],
  templateUrl: "./orders.component.html",
})
export class OrdersComponent implements OnInit {
  orders: OrderOut[] = [];
  loading = true;
  error = "";
  copiedOrderId: number | null = null; // UI feedback for copy

  constructor(private svc: OrdersService) {}
  ngOnInit() {
    this.refresh();
  }

  refresh() {
    this.loading = true;
    this.svc.list().subscribe({
      next: (o) => {
        this.orders = o;
        this.loading = false;
      },
      error: (err) => {
        this.error = err?.error?.detail || "Failed to load orders";
        this.loading = false;
      },
    });
  }

  total(o: OrderOut) {
    return `₹${(o.total_amount_cents / 100).toFixed(2)}`;
  }

  cancel(o: OrderOut) {
    this.svc.cancel(o.id).subscribe({
      next: () => this.refresh(),
      error: (err) => alert(err?.error?.detail || "Cancel failed"),
    });
  }

  // --- New helpers below ---

  async copy(id: number) {
    try {
      await navigator.clipboard.writeText(String(id));
      this.copiedOrderId = id;
      setTimeout(() => (this.copiedOrderId = null), 1200);
    } catch {
      // Fallback if clipboard API is unavailable
      const ta = document.createElement("textarea");
      ta.value = String(id);
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      document.body.removeChild(ta);
      this.copiedOrderId = id;
      setTimeout(() => (this.copiedOrderId = null), 1200);
    }
  }

  statusClass(status: OrderOut["status"]): string {
    switch (status) {
      case "PAID":
        return "badge badge--ok";
      case "PENDING_PAYMENT":
        return "badge badge--warn";
      case "CANCELLED":
        return "badge badge--err";
      default:
        return "badge";
    }
  }

  shortAddress(o: OrderOut): string {
    // Show the first ~60 chars of the shipping address for list view
    const a = o.shipping_address || "";
    return a.length > 60 ? a.slice(0, 57) + "…" : a;
  }
}
