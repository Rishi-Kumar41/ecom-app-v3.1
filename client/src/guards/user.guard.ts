import { inject, PLATFORM_ID } from '@angular/core';
import { isPlatformServer } from '@angular/common';
import { CanActivateFn, Router, RouterStateSnapshot, ActivatedRouteSnapshot } from '@angular/router';
import { AuthService } from '../services/auth.service';

export const userGuard: CanActivateFn = (route: ActivatedRouteSnapshot, state: RouterStateSnapshot) => {
  const platformId = inject(PLATFORM_ID);

  // ✅ Allow during SSR/SSG so prerender can generate contentful HTML
  if (isPlatformServer(platformId)) return true;

  const auth = inject(AuthService);
  const router = inject(Router);

  if (!auth.isLoggedIn()) {
    return router.createUrlTree(['/login'], { queryParams: { returnUrl: state.url } });
  }

  // Only users (customers) are allowed past this guard
  if (auth.userRole && auth.userRole() === 'user') {
    return true;
  }

  // If it's an admin, send to Support instead of shopping routes
  return router.createUrlTree(['/support']);
};