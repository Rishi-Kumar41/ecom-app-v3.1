import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { AssistService } from '../../services/assist.service';

interface Turn {
  role: 'user' | 'assistant';
  text: string;
  ts: number; // timestamp for ordering/debug
}

@Component({
  standalone: true,
  selector: 'app-assist-floating',
  imports: [CommonModule, FormsModule],
  templateUrl: './assist-floating.component.html',
  styleUrls: ['./assist-floating.component.css']
})
export class AssistFloatingComponent implements OnInit {
  // UI state
  open = false;
  sending = false;
  error = '';

  // Query + retrieval options (match backend defaults)
  q = '';
  hybrid = true;   // RAG: vector + BM25 (RRF)
  k = 12;
  products = 5;

  // Transcript (local, simple)
  chat: Turn[] = [];

  // LocalStorage keys (scoped per user)
  private chatKey = 'ecom_assist_chat';
  private prefsKey = 'ecom_assist_prefs';

  constructor(private assist: AssistService) {}

  ngOnInit(): void {
    // Build user-scoped keys to simulate per-session per-login experience
    const uid = this.getUserScopeId();
    if (uid) {
      this.chatKey = `ecom_assist_chat_${uid}`;
      this.prefsKey = `ecom_assist_prefs_${uid}`;
    }

    this.loadChat();
    this.loadPrefs();
  }

  toggle(): void {
    this.open = !this.open;
    this.error = '';
    // optional: persist open state if you want
    this.savePrefs();
  }

  send(): void {
    const query = (this.q || '').trim();
    if (!query || this.sending) return;

    // Show user turn
    this.chat.push({ role: 'user', text: query, ts: Date.now() });
    this.trimChat();
    this.saveChat();

    this.q = '';
    this.error = '';
    this.sending = true;

    this.assist.ask(query, {
      k: this.k,
      products: this.products,
      price_band_pct: 0.15,
      hybrid: this.hybrid
    }).subscribe({
      next: (res) => {
        const text = (res?.answer || '').trim() || '(no answer)';
        this.chat.push({ role: 'assistant', text, ts: Date.now() });
        this.trimChat();
        this.saveChat();
        this.sending = false;
      },
      error: (e) => {
        this.error = e?.error?.detail || 'Assistant failed. Please try again.';
        this.sending = false;
      },
    });
  }

  clear(): void {
    if (this.sending) return;
    this.chat = [];
    this.error = '';
    this.saveChat();
  }

  // -----------------------
  // Persistence helpers
  // -----------------------
  private loadChat(): void {
    try {
      const raw = localStorage.getItem(this.chatKey);
      if (!raw) return;
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed)) {
        // Basic shape guard
        this.chat = parsed
          .filter(x => x && (x.role === 'user' || x.role === 'assistant') && typeof x.text === 'string')
          .map(x => ({ role: x.role, text: x.text, ts: typeof x.ts === 'number' ? x.ts : Date.now() }));
        this.trimChat();
      }
    } catch {
      // ignore corrupted storage
      this.chat = [];
    }
  }

  private saveChat(): void {
    try {
      localStorage.setItem(this.chatKey, JSON.stringify(this.chat));
    } catch {
      // ignore quota errors
    }
  }

  private loadPrefs(): void {
    try {
      const raw = localStorage.getItem(this.prefsKey);
      if (!raw) return;
      const p = JSON.parse(raw);
      // Only apply if types match
      if (typeof p.open === 'boolean') this.open = p.open;
      if (typeof p.hybrid === 'boolean') this.hybrid = p.hybrid;
      if (typeof p.k === 'number') this.k = p.k;
      if (typeof p.products === 'number') this.products = p.products;
    } catch {
      // ignore
    }
  }

  private savePrefs(): void {
    try {
      localStorage.setItem(this.prefsKey, JSON.stringify({
        open: this.open,
        hybrid: this.hybrid,
        k: this.k,
        products: this.products,
      }));
    } catch {
      // ignore
    }
  }

  private trimChat(maxTurns = 40): void {
    // Keep last N turns only (prevents localStorage bloat)
    if (this.chat.length > maxTurns) {
      this.chat = this.chat.slice(this.chat.length - maxTurns);
    }
  }

  /**
   * Determine user scope id from your auth storage.
   * Your app already saves user JSON in localStorage (e.g., 'ecom_user').
   * We use id first, fallback to email, else no scoping.
   */
  private getUserScopeId(): string | null {
    try {
      const raw = localStorage.getItem('ecom_user');
      if (!raw) return null;
      const u = JSON.parse(raw);
      return String(u?.id ?? u?.email ?? '').trim() || null;
    } catch {
      return null;
    }
  }
}