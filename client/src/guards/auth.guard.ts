import { inject, PLATFORM_ID } from '@angular/core';
import { isPlatformServer } from '@angular/common';
import { CanActivateFn, Router } from '@angular/router';
import { AuthService } from '../services/auth.service';

export const authGuard: CanActivateFn = (_route, state) => {
  const platformId = inject(PLATFORM_ID);

  // ✅ Allow during SSR/SSG (no browser auth context during prerender)
  if (isPlatformServer(platformId)) return true;

  const auth = inject(AuthService);
  const router = inject(Router);
  
  if (auth.isLoggedIn()) return true;

  // Not logged in → send to login and remember where user wanted to go
  router.navigate(['/login'], { queryParams: { returnUrl: state.url } });
  return false;

};
//router.navigate(['/login'], { queryParams: { returnUrl: router.url } });