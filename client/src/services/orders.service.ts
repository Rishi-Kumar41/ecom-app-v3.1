import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { ApiService } from './api.service';


export interface OrderItemIn { product_id: number; quantity: number; }
export interface OrderCreate {
  items: OrderItemIn[];
  payment_method: string;
  shipping_address: string;
  contact_name: string;
  contact_email: string;
  contact_phone: string;
}

export interface OrderItemOut {
  product_id: number;
  quantity: number;
  unit_price_cents: number;
}

export interface OrderOut {
  id: number;
  status: 'PENDING_PAYMENT' | 'PAID' | 'CANCELLED';
  total_amount_cents: number;
  payment_method?: string;
  shipping_address?: string;
  contact_name?: string;
  contact_email?: string;
  contact_phone?: string;
  items: OrderItemOut[];
}

@Injectable({ providedIn: 'root' })
export class OrdersService {

  constructor(private http: HttpClient, private api: ApiService) {}

  list(): Observable<OrderOut[]> {
    return this.http.get<OrderOut[]>(`${this.api.base}/orders`);
  }

  get(id: number): Observable<OrderOut> {
    return this.http.get<OrderOut>(`${this.api.base}/orders/${id}`);
  }

  create(payload: OrderCreate): Observable<OrderOut> {
    return this.http.post<OrderOut>(`${this.api.base}/orders`, payload);
  }

  // Start Stripe checkout session
  pay(orderId: number): Observable<{ checkout_url: string }> {
    return this.http.post<{ checkout_url: string }>(`${this.api.base}/payments/stripe-session/${orderId}`, {});
  }

  cancel(orderId: number): Observable<OrderOut> {
    return this.http.post<OrderOut>(`${this.api.base}/orders/${orderId}/cancel`, {});
  }
}