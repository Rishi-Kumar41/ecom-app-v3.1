import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

// Assumes you already have ApiService that exposes API base URL (e.g., http://127.0.0.1:8000)
import { ApiService } from './api.service';

export interface AnswerOut {
  /** Backend returns only the 'answer' text (no items in payload). */
  answer: string;
}

export interface AskOptions {
  /** Top-k chunks for initial recall in RAG (default 12). */
  k?: number;
  /** Max number of products to present in the model prompt context (default 5). */
  products?: number;
  /** +/- band around a parsed price (default 0.15 = ±15%). */
  price_band_pct?: number;
  /** Use hybrid retrieval (vector + BM25 fused via RRF). Default true. */
  hybrid?: boolean;
}

@Injectable({ providedIn: 'root' })
export class AssistService {
  constructor(private http: HttpClient, private api: ApiService) {}

  /**
   * Ask the RAG assistant a question. Returns a single 'answer' string.
   * Retrieval is performed server-side; no items are returned to the UI.
   */
  ask(query: string, opts: AskOptions = {}): Observable<AnswerOut> {
    const body = {
      query,
      k: opts.k ?? 12,
      products: opts.products ?? 5,
      price_band_pct: opts.price_band_pct ?? 0.15,
      hybrid: opts.hybrid ?? true
    };

    return this.http.post<AnswerOut>(`${this.api.base}/ai/answer`, body);
  }
}
