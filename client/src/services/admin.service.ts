// client/src/services/admin.service.ts
import { Injectable } from "@angular/core";
import { HttpClient, HttpParams } from "@angular/common/http";
import { ApiService } from "./api.service";
import { Observable } from "rxjs";

export interface AdminCreateProductPayload {
  name: string;
  category?: string | null;
  price_cents: number; // integer paise
  stock: number; // integer qty
  description?: string | null;
  image_url?: string | null;
  specs?: Record<string, string>;
}

export interface AdminSearchItem {
  score: number;
  snippet: string;
  source: 'product' | 'order' | 'user' | 'policy';
  product_id?: number | null;
  title?: string | null;
  metadata?: any;
}
export interface AdminSearchResponse {
  items: AdminSearchItem[];
  total: number;
}

@Injectable({ providedIn: "root" })
export class AdminService {
  constructor(
    private http: HttpClient,
    private api: ApiService,
  ) {}

  createProduct(payload: AdminCreateProductPayload): Observable<any> {
    return this.http.post<any>(`${this.api.base}/admin/products`, payload);
  }
  generateDescription(payload: any): Observable<any> {
    return this.http.post<any>(
      `${this.api.base}/ai/generate-description`,
      payload,
    );
  }

  //search admin documents (vector-cosine)
  /**
   * Admin universal search over admin_documents (vector; optional hybrid RRF).
   * @param q query text (optional; if empty, backend returns recent items)
   * @param k top-k results (default 10)
   * @param type filter by source: product|order|user|policy|any
   * @param hybrid fuse vector + BM25 (RRF). Default false for Support UI (toggleable).
   */
  search(q: string | null, k = 10, type: string = 'any', hybrid = false): Observable<AdminSearchResponse> {
    let params = new HttpParams()
      .set('k', String(k))
      .set('type', (type || 'any').toLowerCase());
    if (q && q.trim()) params = params.set('q', q.trim());
    if (hybrid) params = params.set('hybrid', 'true');

    return this.http.get<AdminSearchResponse>(`${this.api.base}/admin/search`, { params });
  }
}
