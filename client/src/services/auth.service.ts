import { Injectable, inject, PLATFORM_ID } from "@angular/core";
import { isPlatformBrowser } from "@angular/common";
import {
  HttpClient,
  HttpInterceptorFn,
  HttpHeaders,
} from "@angular/common/http";
import { Router } from "@angular/router";
import { ApiService } from "./api.service";
import { catchError } from 'rxjs/operators';
import { throwError } from 'rxjs';
import { CartService } from './cart.service';

interface LoginResponse {
  access_token: string;
  token_type: string;
}
// export interface User { id: number; name: string; email: string; }

// 1) EXTENDing User with the new optional fields
export interface User {
  id: number;
  name: string;
  email: string;
  role: 'user' | 'admin'; 
  default_shipping_address?: string; // <-- NEW
  default_contact_phone?: string; // <-- NEW
}

@Injectable({ providedIn: "root" })
export class AuthService {
  private tokenKey = "ecom_token";
  private userKey = "ecom_user";
  private cartKey  = 'ecom_cart';

private platformId = inject(PLATFORM_ID);
private isBrowser = isPlatformBrowser(this.platformId);

  constructor(
    private http: HttpClient,
    private api: ApiService,
    private router: Router,
    private cart: CartService,
  ) {}
  register(payload: { name: string; email: string; password: string }) {
    return this.http.post<User>(`${this.api.base}/auth/register`, payload);
  }
  login(email: string, password: string) {
    const body = new URLSearchParams();
    body.set("username", email);
    body.set("password", password);
    return this.http.post<LoginResponse>(
      `${this.api.base}/auth/login`,
      body.toString(),
      {
        headers: new HttpHeaders({
          "Content-Type": "application/x-www-form-urlencoded",
        }),
      },
    );
  }
  saveToken(token: string) {
    if (this.isBrowser) localStorage.setItem(this.tokenKey, token);
  }
  token(): string | null {
    return this.isBrowser ? localStorage.getItem(this.tokenKey) : null;
  }
  isLoggedIn(): boolean {
    return !!this.token();
  }
  
logout(redirectTo: string = '/login') {
  try { this.cart?.clear?.(); } catch {}

  if (this.isBrowser) {
    // Clear session/auth data
    localStorage.removeItem(this.tokenKey);
    localStorage.removeItem(this.userKey);
    localStorage.removeItem(this.cartKey);

    // Clear Assist chat/session (per-user + generic)
    try {
      const raw = localStorage.getItem('ecom_user'); // safe now (browser only)
      let uid = '';
      if (raw) {
        const u = JSON.parse(raw);
        uid = String(u?.id ?? u?.email ?? '').trim();
      }

      localStorage.removeItem('ecom_assist_chat');
      localStorage.removeItem('ecom_assist_prefs');

      if (uid) {
        localStorage.removeItem(`ecom_assist_chat_${uid}`);
        localStorage.removeItem(`ecom_assist_prefs_${uid}`);
      }
    } catch {}
  }

  this.router.navigate([redirectTo]);
}


  fetchMe() {
    return this.http.get<User>(`${this.api.base}/me`);
  }
  setUser(u: User) {
    if (this.isBrowser) localStorage.setItem(this.userKey, JSON.stringify(u));
  }
  user(): User | null {
    if (!this.isBrowser) return null;
    const raw = localStorage.getItem(this.userKey);
    return raw ? JSON.parse(raw) : null;
  }
  userName(): string {
    return this.user()?.name ?? "User";
  }

  // 2) ADD a method to save/update the default address on the server
  saveAddress(payload: {
    default_shipping_address: string;
    default_contact_phone?: string;
  }) {
    return this.http.put<User>(`${this.api.base}/me/address`, payload);
  }

  // 3) OPTIONAL helper getters used later for prefilling checkout
  savedAddress(): string {
    return this.user()?.default_shipping_address ?? "";
  }
  savedPhone(): string {
    return this.user()?.default_contact_phone ?? "";
  }


  isAdmin(): boolean {
    return this.user()?.role === 'admin';
  }

  userRole(): 'user' | 'admin' | undefined {
    return this.user()?.role;
  }

}

export const authInterceptor: HttpInterceptorFn = (req, next) => {
  const platformId = inject(PLATFORM_ID);
  const router = inject(Router);

  // ✅ Server/SSG: do not touch localStorage/window
  if (!isPlatformBrowser(platformId)) {
    return next(req);
  }

  const token = localStorage.getItem("ecom_token");
  if (token) {
    req = req.clone({ setHeaders: { Authorization: `Bearer ${token}` } });
  }

  return next(req).pipe(
    catchError((err) => {
      if (err?.status === 401) {
        localStorage.removeItem('ecom_token');
        localStorage.removeItem('ecom_user');

        const returnUrl = window.location.pathname + window.location.search;
        router.navigate(['/login'], { queryParams: { returnUrl } });
      }
      return throwError(() => err);
    })
  );
};
