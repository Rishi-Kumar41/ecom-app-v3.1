import { Injectable } from '@angular/core';
import { HttpClient, HttpInterceptorFn, HttpHeaders } from '@angular/common/http';
import { Router } from '@angular/router';
import { ApiService } from './api.service';

interface LoginResponse { access_token: string; token_type: string; }
// export interface User { id: number; name: string; email: string; }

// 1) EXTENDing User with the new optional fields
export interface User {
  id: number;
  name: string;
  email: string;
  default_shipping_address?: string;   // <-- NEW
  default_contact_phone?: string;      // <-- NEW
}

@Injectable({ providedIn: 'root' })
export class AuthService {
  private tokenKey = 'ecom_token';
  private userKey = 'ecom_user';
  constructor(private http: HttpClient, private api: ApiService, private router: Router) {}
  register(payload: {name: string; email: string; password: string}) { return this.http.post<User>(`${this.api.base}/auth/register`, payload); }
  login(email: string, password: string) {
    const body = new URLSearchParams(); body.set('username', email); body.set('password', password);
    return this.http.post<LoginResponse>(`${this.api.base}/auth/login`, body.toString(), { headers: new HttpHeaders({'Content-Type': 'application/x-www-form-urlencoded'}) }); }
  saveToken(token: string) { localStorage.setItem(this.tokenKey, token); }
  token(): string | null { return localStorage.getItem(this.tokenKey); }
  isLoggedIn(): boolean { return !!this.token(); }
  logout() { localStorage.removeItem(this.tokenKey); localStorage.removeItem(this.userKey); this.router.navigateByUrl('/'); }
  fetchMe() { return this.http.get<User>(`${this.api.base}/me`); }
  setUser(u: User) { localStorage.setItem(this.userKey, JSON.stringify(u)); }
  user(): User | null { const raw = localStorage.getItem(this.userKey); return raw ? JSON.parse(raw) : null; }
  userName(): string { return this.user()?.name ?? 'User'; }

  // 2) ADD a method to save/update the default address on the server
  saveAddress(payload: { default_shipping_address: string; default_contact_phone?: string; }) {
    return this.http.put<User>(`${this.api.base}/me/address`, payload);
  }

  // 3) OPTIONAL helper getters used later for prefilling checkout
  savedAddress(): string {
    return this.user()?.default_shipping_address ?? '';
  }
  savedPhone(): string {
    return this.user()?.default_contact_phone ?? '';
  }
}
export const authInterceptor: HttpInterceptorFn = (req, next) => { const token = localStorage.getItem('ecom_token'); if (token) req = req.clone({ setHeaders: { Authorization: `Bearer ${token}` }}); return next(req); };
