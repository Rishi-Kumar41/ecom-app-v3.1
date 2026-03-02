import { bootstrapApplication } from '@angular/platform-browser';
import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { provideRouter } from '@angular/router';
import { AppComponent } from './app.component';
import { routes } from './app.routes';
import { authInterceptor } from './services/auth.service';

bootstrapApplication(AppComponent, {
  providers: [ provideRouter(routes), provideHttpClient(withInterceptors([authInterceptor])) ]
}).catch(err => console.error(err));
