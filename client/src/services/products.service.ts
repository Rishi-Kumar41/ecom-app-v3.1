import { Injectable } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { ApiService } from './api.service';

export interface Product { id: number; name: string; description: string; category?: string; price_cents: number; image_url?: string; stock: number; specs?: Record<string,string>; }
export interface ProductQuery { q?: string; category?: string; min_price_cents?: number; max_price_cents?: number; in_stock?: boolean; sort?: string; }

@Injectable({ providedIn: 'root' })
export class ProductsService {
  constructor(private http: HttpClient, private api: ApiService) {}
  list(query: ProductQuery = {}) { let params = new HttpParams(); Object.entries(query).forEach(([k,v]) => { if (v !== undefined && v !== null && v !== '') params = params.set(k, String(v)); }); return this.http.get<Product[]>(`${this.api.base}/products`, { params }); }
  categories() { return this.http.get<string[]>(`${this.api.base}/products/categories`); }
  get(id: number) { return this.http.get<Product>(`${this.api.base}/products/${id}`); }
}
