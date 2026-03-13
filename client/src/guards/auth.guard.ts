import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { AuthService } from '../services/auth.service';

export const authGuard: CanActivateFn = (_route, state) => {
  const auth = inject(AuthService);
  const router = inject(Router);
  
  if (auth.isLoggedIn()) return true;

  // Not logged in → send to login and remember where user wanted to go
  router.navigate(['/login'], { queryParams: { returnUrl: state.url } });
  return false;

};
//router.navigate(['/login'], { queryParams: { returnUrl: router.url } });