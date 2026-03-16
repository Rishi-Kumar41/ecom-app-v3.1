// client/src/services/admin.service.ts
import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { ApiService } from './api.service';
import { Observable } from 'rxjs';

export interface AdminCreateProductPayload {
  name: string;
  category?: string | null;
  price_cents: number;        // integer paise
  stock: number;              // integer qty
  description?: string | null;
  image_url?: string | null;
}

@Injectable({ providedIn: 'root' })
export class AdminService {
  constructor(private http: HttpClient, private api: ApiService) {}

  createProduct(payload: AdminCreateProductPayload): Observable<any> {
    // Backend endpoint already exists under /admin/products and requires admin role.
    return this.http.post<any>(`${this.api.base}/admin/products`, payload);
  }
}