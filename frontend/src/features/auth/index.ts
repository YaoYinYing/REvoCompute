import { createIcons, CheckCircle2, RefreshCw, XCircle } from 'lucide';
import {
  forgotPassword,
  getCaptcha,
  getRegistrationCapability,
  login,
  register,
  resendVerification,
  resetPassword,
  verifyEmail,
  type CaptchaChallenge,
  type RegistrationRequest,
} from '../../api/app-api';
import type { AppShell } from '../../app/shell';
import { appAsset } from '../../app/assets';
import { academicPositionOptions } from '../../app/domain-vocabulary';
import './auth.css';

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback;
}

function setStatus(element: HTMLElement, message = '', tone: 'success' | 'error' | 'info' = 'info'): void {
  element.textContent = message;
  element.className = `form-status status-${tone}`;
  element.hidden = !message;
}

function fieldValue(form: HTMLFormElement, name: string): string {
  return String(new FormData(form).get(name) || '');
}

function consumeOpaqueToken(): string {
  const url = new URL(location.href);
  const token = url.searchParams.get('token') || '';
  if (url.searchParams.has('token')) {
    url.searchParams.delete('token');
    history.replaceState(history.state, '', `${url.pathname}${url.search}${url.hash}`);
  }
  return token;
}

export function safeReturnTo(search: string, origin = 'https://revocompute.invalid'): string {
  const requested = new URLSearchParams(search).get('return_to') || '/compute/dashboard';
  if (!requested.startsWith('/') || requested.startsWith('//') || requested.includes('\\')) return '/compute/dashboard';
  try {
    const resolved = new URL(requested, origin);
    if (resolved.origin !== origin) return '/compute/dashboard';
    return `${resolved.pathname}${resolved.search}${resolved.hash}`;
  } catch {
    return '/compute/dashboard';
  }
}

function authFrame(root: HTMLElement, title: string, description: string, alternate: string): HTMLElement {
  root.innerHTML = `
    <main class="auth-page">
      <div class="auth-route-link">${alternate}</div>
      <section class="auth-panel">
        <a class="auth-brand" href="/"><img src="${appAsset('logo.svg')}" alt="" width="38" height="38"><span>REvoCompute</span></a>
        <h1>${title}</h1><p class="auth-description">${description}</p>
        <div data-auth-content></div>
      </section>
    </main>`;
  return root.querySelector<HTMLElement>('[data-auth-content]')!;
}

export function mountLogin(root: HTMLElement, shell: AppShell): void {
  document.title = 'Sign in | REvoCompute';
  const content = authFrame(root, 'Sign in', 'Access your scientific compute workspace.', '<a href="/compute/register">Create an account</a>');
  content.innerHTML = `
    <form class="auth-form" data-login-form>
      <label>Username or email<input name="username" autocomplete="username" required autofocus></label>
      <label>Password<input name="password" type="password" autocomplete="current-password" required></label>
      <button class="primary-button auth-submit" type="submit">Sign in</button>
      <p class="form-status" data-login-status role="alert" hidden></p>
    </form>
    <button class="link-button forgot-toggle" type="button" aria-expanded="false">Forgot your password?</button>
    <section class="forgot-password" hidden>
      <h2>Reset your password</h2><p>Enter your account email. The response is the same whether an account exists.</p>
      <form class="auth-form compact" data-forgot-form>
        <label>Email<input name="email" type="email" autocomplete="email" required></label>
        <button class="secondary-button" type="submit">Send reset link</button>
        <p class="form-status" data-forgot-status role="status" hidden></p>
      </form>
    </section>`;
  const loginForm = content.querySelector<HTMLFormElement>('[data-login-form]')!;
  const loginStatus = content.querySelector<HTMLElement>('[data-login-status]')!;
  loginForm.addEventListener('submit', async event => {
    event.preventDefault();
    const button = loginForm.querySelector<HTMLButtonElement>('button')!;
    button.disabled = true; button.textContent = 'Signing in...'; setStatus(loginStatus);
    try {
      const response = await login(fieldValue(loginForm, 'username').trim(), fieldValue(loginForm, 'password'));
      setStatus(loginStatus, `Signed in as ${response.username}. Opening your workspace...`, 'success');
      location.assign(safeReturnTo(location.search, location.origin));
    } catch (error) {
      setStatus(loginStatus, errorMessage(error, 'Sign in failed. Try again.'), 'error');
      shell.notify('Sign in failed.', 'error');
      button.disabled = false; button.textContent = 'Sign in';
    }
  });
  const toggle = content.querySelector<HTMLButtonElement>('.forgot-toggle')!;
  const forgot = content.querySelector<HTMLElement>('.forgot-password')!;
  toggle.addEventListener('click', () => {
    forgot.hidden = !forgot.hidden;
    toggle.setAttribute('aria-expanded', String(!forgot.hidden));
    if (!forgot.hidden) forgot.querySelector<HTMLInputElement>('input')?.focus();
  });
  const forgotForm = content.querySelector<HTMLFormElement>('[data-forgot-form]')!;
  const forgotStatus = content.querySelector<HTMLElement>('[data-forgot-status]')!;
  forgotForm.addEventListener('submit', async event => {
    event.preventDefault();
    const button = forgotForm.querySelector<HTMLButtonElement>('button')!;
    button.disabled = true; button.textContent = 'Sending...'; setStatus(forgotStatus);
    try {
      const response = await forgotPassword(fieldValue(forgotForm, 'email').trim());
      setStatus(forgotStatus, response.message, 'success'); forgotForm.reset();
    } catch (error) {
      setStatus(forgotStatus, errorMessage(error, 'The reset request failed. Try again.'), 'error');
    } finally {
      button.disabled = false; button.textContent = 'Send reset link';
    }
  });
}

function registrationForm(): string {
  const options = academicPositionOptions.map(([value, label]) => `<option value="${value}">${label}</option>`).join('');
  return `
    <form class="auth-form registration-form" data-register-form>
      <div class="form-columns">
        <label>Username<input name="username" minlength="3" maxlength="64" autocomplete="username" required></label>
        <label>Email<input name="email" type="email" autocomplete="email" required></label>
        <label>Full name<input name="full_name" maxlength="128" autocomplete="name" required></label>
        <label>Affiliation<input name="affiliation" maxlength="256" autocomplete="organization" required></label>
        <label>Position<select name="position" required><option value="">Select your position</option>${options}</select></label>
        <label>PI or supervisor<input name="pi_name" maxlength="128" required></label>
      </div>
      <label>Password<input name="password" type="password" minlength="8" autocomplete="new-password" required><small>Use at least 8 characters.</small></label>
      <label class="checkbox-control"><input name="terms_agreed" type="checkbox" required><span>I agree to the <a href="/compute/terms" target="_blank" rel="noopener noreferrer">Terms of Service</a>.</span></label>
      <fieldset class="captcha-field"><legend>Human verification</legend><div><strong data-captcha-question>Loading challenge...</strong><input name="captcha_answer" required autocomplete="off" aria-label="CAPTCHA answer"><button class="icon-button" type="button" data-captcha-refresh title="New challenge" aria-label="Load a new CAPTCHA challenge"><i data-lucide="refresh-cw"></i></button></div></fieldset>
      <button class="primary-button auth-submit" type="submit">Create account</button>
      <p class="form-status" data-register-status role="alert" hidden></p>
      <div class="resend-verification" hidden><p>Did not receive the email?</p><button class="secondary-button" type="button">Resend verification email</button></div>
    </form>`;
}

export async function mountRegister(root: HTMLElement): Promise<void> {
  document.title = 'Create account | REvoCompute';
  const content = authFrame(root, 'Create an account', 'Register to submit and track scientific compute tasks.', '<a href="/compute/login">Sign in</a>');
  content.innerHTML = '<p class="loading-state">Checking registration availability...</p>';
  try {
    const capability = await getRegistrationCapability();
    if (!capability.enabled || !capability.email_available) {
      content.innerHTML = `<div class="inline-state state-unavailable"><h2>Registration unavailable</h2><p>${capability.enabled ? 'Email service is not available on this server.' : 'Account registration is disabled on this server.'}</p><a class="secondary-button" href="/compute/login">Return to sign in</a></div>`;
      return;
    }
  } catch (error) {
    content.innerHTML = '<div class="inline-state state-error"><h2>Registration status unavailable</h2><p data-error></p></div>';
    content.querySelector<HTMLElement>('[data-error]')!.textContent = errorMessage(error, 'Try again after the server is available.');
    return;
  }
  content.innerHTML = registrationForm();
  createIcons({ icons: { RefreshCw }, root: content });
  const form = content.querySelector<HTMLFormElement>('[data-register-form]')!;
  const question = form.querySelector<HTMLElement>('[data-captcha-question]')!;
  const refresh = form.querySelector<HTMLButtonElement>('[data-captcha-refresh]')!;
  const status = form.querySelector<HTMLElement>('[data-register-status]')!;
  const answer = form.elements.namedItem('captcha_answer') as HTMLInputElement;
  let challenge: CaptchaChallenge | null = null;
  let registeredEmail = '';
  const loadCaptcha = async (): Promise<void> => {
    refresh.disabled = true; answer.disabled = true; question.textContent = 'Loading challenge...';
    try {
      challenge = await getCaptcha(); question.textContent = challenge.question; answer.value = ''; answer.disabled = false;
    } catch (error) {
      challenge = null; question.textContent = errorMessage(error, 'Challenge unavailable.');
    } finally { refresh.disabled = false; }
  };
  refresh.addEventListener('click', () => { void loadCaptcha(); });
  await loadCaptcha();
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (!challenge) { setStatus(status, 'Load a CAPTCHA challenge before creating your account.', 'error'); return; }
    const data = new FormData(form);
    const payload: RegistrationRequest = {
      username: String(data.get('username') || '').trim(), email: String(data.get('email') || '').trim(),
      password: String(data.get('password') || ''), full_name: String(data.get('full_name') || '').trim(),
      affiliation: String(data.get('affiliation') || '').trim(), position: String(data.get('position') || '') as RegistrationRequest['position'],
      pi_name: String(data.get('pi_name') || '').trim(), terms_agreed: true,
      captcha_token: challenge.token, captcha_answer: String(data.get('captcha_answer') || '').trim(),
    };
    const submit = form.querySelector<HTMLButtonElement>('[type="submit"]')!;
    submit.disabled = true; submit.textContent = 'Creating account...'; setStatus(status);
    try {
      const response = await register(payload);
      registeredEmail = payload.email; form.reset(); challenge = null;
      setStatus(status, response.message, 'success');
      form.querySelector<HTMLElement>('.resend-verification')!.hidden = false;
    } catch (error) {
      setStatus(status, errorMessage(error, 'Registration failed. Review the form and try again.'), 'error');
      await loadCaptcha();
    } finally { submit.disabled = false; submit.textContent = 'Create account'; }
  });
  const resend = form.querySelector<HTMLButtonElement>('.resend-verification button')!;
  resend.addEventListener('click', async () => {
    resend.disabled = true; resend.textContent = 'Sending...';
    try { setStatus(status, (await resendVerification(registeredEmail)).message, 'success'); }
    catch (error) { setStatus(status, errorMessage(error, 'Verification email could not be sent.'), 'error'); }
    finally { resend.disabled = false; resend.textContent = 'Resend verification email'; }
  });
}

export function mountResetPassword(root: HTMLElement): void {
  document.title = 'Reset password | REvoCompute';
  const token = consumeOpaqueToken();
  const content = authFrame(root, 'Reset your password', 'Choose a new password for your account.', '<a href="/compute/login">Return to sign in</a>');
  if (!token) {
    content.innerHTML = '<div class="inline-state state-error"><h2>Reset link incomplete</h2><p>Open the complete link from your password reset email.</p></div>';
    return;
  }
  content.innerHTML = `<form class="auth-form" data-reset-form><label>New password<input name="password" type="password" minlength="8" autocomplete="new-password" required autofocus><small>Use at least 8 characters.</small></label><button class="primary-button auth-submit" type="submit">Set password</button><p class="form-status" role="alert" hidden></p></form>`;
  const form = content.querySelector<HTMLFormElement>('form')!;
  const status = form.querySelector<HTMLElement>('.form-status')!;
  form.addEventListener('submit', async event => {
    event.preventDefault(); const button = form.querySelector<HTMLButtonElement>('button')!;
    button.disabled = true; button.textContent = 'Setting password...';
    try {
      setStatus(status, (await resetPassword(token, fieldValue(form, 'password'))).message, 'success');
      form.querySelector<HTMLInputElement>('input')!.value = '';
      button.textContent = 'Password updated';
      window.setTimeout(() => location.assign('/compute/login'), 1200);
    } catch (error) {
      setStatus(status, errorMessage(error, 'Password reset failed. Request a new link.'), 'error');
      button.disabled = false; button.textContent = 'Set password';
    }
  });
}

export async function mountVerifyEmail(root: HTMLElement): Promise<void> {
  document.title = 'Verify email | REvoCompute';
  const token = consumeOpaqueToken();
  const content = authFrame(root, 'Verify your email', 'Confirming the link from your registration email.', '<a href="/compute/login">Return to sign in</a>');
  if (!token) {
    content.innerHTML = '<div class="verification-result state-error"><i data-lucide="x-circle"></i><h2>Verification link incomplete</h2><p>Open the complete link from your verification email.</p></div>';
    createIcons({ icons: { XCircle }, root: content }); return;
  }
  content.innerHTML = '<p class="loading-state">Verifying your email...</p>';
  try {
    const response = await verifyEmail(token);
    content.innerHTML = `<div class="verification-result state-success"><i data-lucide="check-circle-2"></i><h2>Email verified</h2><p data-message></p>${response.registration_pending ? '<p>An administrator must approve the account before you can sign in.</p>' : '<a class="primary-button" href="/compute/login">Sign in</a>'}</div>`;
    content.querySelector<HTMLElement>('[data-message]')!.textContent = response.message;
    createIcons({ icons: { CheckCircle2 }, root: content });
  } catch (error) {
    content.innerHTML = '<div class="verification-result state-error"><i data-lucide="x-circle"></i><h2>Verification failed</h2><p data-error></p><a class="secondary-button" href="/compute/login">Return to sign in</a></div>';
    content.querySelector<HTMLElement>('[data-error]')!.textContent = errorMessage(error, 'The link is invalid or expired.');
    createIcons({ icons: { XCircle }, root: content });
  }
}
