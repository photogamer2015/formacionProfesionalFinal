import os
import secrets
import smtplib
import time
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid

from django import forms
from django.conf import settings
from django.contrib.auth import get_user_model, login as auth_login
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.views import LoginView
from django.http import HttpResponseRedirect
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from django.views.generic.edit import FormView


LOGIN_CAPTCHA_QUESTION_SESSION_KEY = 'login_captcha_question'
LOGIN_CAPTCHA_ANSWER_SESSION_KEY = 'login_captcha_answer'

LOGIN_MFA_USER_ID_SESSION_KEY = 'login_mfa_user_id'
LOGIN_MFA_CODE_HASH_SESSION_KEY = 'login_mfa_code_hash'
LOGIN_MFA_EXPIRES_AT_SESSION_KEY = 'login_mfa_expires_at'
LOGIN_MFA_ATTEMPTS_SESSION_KEY = 'login_mfa_attempts'
LOGIN_MFA_EMAIL_SESSION_KEY = 'login_mfa_email'
LOGIN_MFA_REDIRECT_SESSION_KEY = 'login_mfa_redirect_to'
LOGIN_MFA_EMAIL_TO_SAVE_SESSION_KEY = 'login_mfa_email_to_save'


class EmailCodeDeliveryError(Exception):
    pass


def _env(name, default=''):
    return (os.environ.get(name, default) or '').strip()


def _env_bool(name, default=False):
    value = _env(name)
    if not value:
        return default
    return value.lower() in {'1', 'true', 'yes', 'on', 'si'}


def _env_int(name, default):
    try:
        return int(_env(name, str(default)))
    except ValueError:
        return default


def generar_captcha_login(request):
    left = secrets.randbelow(8) + 2
    right = secrets.randbelow(8) + 2
    operator = '+' if secrets.randbelow(2) == 0 else 'x'
    answer = left + right if operator == '+' else left * right
    question = f'{left} {operator} {right}'

    request.session[LOGIN_CAPTCHA_QUESTION_SESSION_KEY] = question
    request.session[LOGIN_CAPTCHA_ANSWER_SESSION_KEY] = str(answer)
    return question


def generar_codigo_verificacion():
    return f'{secrets.randbelow(1000000):06d}'


def limpiar_captcha_login(request):
    request.session.pop(LOGIN_CAPTCHA_QUESTION_SESSION_KEY, None)
    request.session.pop(LOGIN_CAPTCHA_ANSWER_SESSION_KEY, None)


def limpiar_reto_correo(request):
    for key in (
        LOGIN_MFA_USER_ID_SESSION_KEY,
        LOGIN_MFA_CODE_HASH_SESSION_KEY,
        LOGIN_MFA_EXPIRES_AT_SESSION_KEY,
        LOGIN_MFA_ATTEMPTS_SESSION_KEY,
        LOGIN_MFA_EMAIL_SESSION_KEY,
        LOGIN_MFA_REDIRECT_SESSION_KEY,
        LOGIN_MFA_EMAIL_TO_SAVE_SESSION_KEY,
    ):
        request.session.pop(key, None)


def tiempo_vida_codigo():
    return _env_int('MFA_CODE_TTL_SECONDS', 300)


def max_intentos_codigo():
    return _env_int('MFA_CODE_MAX_ATTEMPTS', 5)


def mascara_correo(email):
    local, separator, domain = email.partition('@')
    if not separator:
        return email
    if len(local) <= 2:
        local_mask = local[:1] + '*'
    else:
        local_mask = local[:2] + ('*' * max(2, len(local) - 2))
    return f'{local_mask}@{domain}'


def destinatario_codigo(user):
    user_email = (getattr(user, 'email', '') or '').strip()
    if user_email:
        return user_email

    fallback_email = (
        _env('MFA_EMAIL_RECIPIENT')
        or _env('MFA_EMAIL_TO')
        or _env('MFA_EMAIL_HOST_USER')
        or _env('EMAIL_HOST_USER')
    )
    if fallback_email:
        return fallback_email

    raise EmailCodeDeliveryError('No hay un correo configurado para recibir el codigo.')


def config_correo_mfa():
    username = _env('MFA_EMAIL_HOST_USER') or _env('EMAIL_HOST_USER')
    password = (_env('MFA_EMAIL_HOST_PASSWORD') or _env('EMAIL_HOST_PASSWORD')).replace(' ', '')
    if not username or not password:
        raise EmailCodeDeliveryError('Faltan las credenciales del correo MFA.')

    return {
        'host': _env('MFA_EMAIL_HOST', 'smtp.gmail.com'),
        'port': _env_int('MFA_EMAIL_PORT', 465),
        'use_ssl': _env_bool('MFA_EMAIL_USE_SSL', True),
        'use_tls': _env_bool('MFA_EMAIL_USE_TLS', False),
        'username': username,
        'password': password,
        'from_email': _env('MFA_EMAIL_FROM', username),
    }


def enviar_codigo_login(codigo, user, recipient):
    config = config_correo_mfa()
    ttl_minutes = max(1, tiempo_vida_codigo() // 60)
    display_name = user.get_full_name() or user.get_username()
    from_name = _env('MFA_EMAIL_FROM_NAME', 'Formacion Profesional EC')
    reply_to = _env('MFA_EMAIL_REPLY_TO', config['from_email'])
    sender_domain = config['from_email'].split('@')[-1]
    plain_body = (
        'Formacion Profesional EC\n\n'
        f'Codigo de acceso: {codigo}\n\n'
        f'Usalo para completar el inicio de sesion de {display_name}. '
        f'Este codigo vence en {ttl_minutes} minutos.\n\n'
        'Si no solicitaste este acceso, puedes ignorar este mensaje.\n\n'
        f'Remitente oficial: {config["from_email"]}\n'
    )
    html_body = f"""\
<!doctype html>
<html>
  <body style="margin:0; padding:0; background:#f6f8fb; font-family:Arial, Helvetica, sans-serif; color:#172033;">
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#f6f8fb; padding:24px 0;">
      <tr>
        <td align="center">
          <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:520px; background:#ffffff; border:1px solid #e5e9f2; border-radius:12px;">
            <tr>
              <td style="padding:28px 28px 8px 28px;">
                <h1 style="margin:0; color:#1a237e; font-size:22px; line-height:1.3;">Codigo de acceso</h1>
                <p style="margin:8px 0 0 0; color:#5f6f89; font-size:15px;">Formacion Profesional EC</p>
              </td>
            </tr>
            <tr>
              <td style="padding:18px 28px;">
                <p style="margin:0 0 16px 0; font-size:15px; line-height:1.5;">Hola {display_name}, usa este codigo para completar tu inicio de sesion:</p>
                <div style="font-size:32px; font-weight:700; letter-spacing:6px; color:#1a237e; background:#eef4ff; border:1px solid #dbe3ef; border-radius:10px; padding:18px; text-align:center;">{codigo}</div>
                <p style="margin:18px 0 0 0; font-size:14px; line-height:1.5; color:#4a5568;">Este codigo vence en {ttl_minutes} minutos. Si no solicitaste este acceso, puedes ignorar este mensaje.</p>
              </td>
            </tr>
            <tr>
              <td style="padding:16px 28px 28px 28px; color:#718096; font-size:12px; line-height:1.5; border-top:1px solid #edf2f7;">
                Remitente oficial: {config["from_email"]}
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>
"""

    message = EmailMessage()
    message['Subject'] = _env('MFA_EMAIL_SUBJECT', 'Codigo de acceso Formacion Profesional EC')
    message['From'] = formataddr((from_name, config['from_email']))
    message['To'] = recipient
    message['Reply-To'] = reply_to
    message['Date'] = formatdate(localtime=True)
    message['Message-ID'] = make_msgid(domain=sender_domain)
    message.set_content(plain_body)
    message.add_alternative(html_body, subtype='html')

    try:
        if config['use_ssl']:
            with smtplib.SMTP_SSL(config['host'], config['port'], timeout=15) as server:
                server.login(config['username'], config['password'])
                server.send_message(message)
        else:
            with smtplib.SMTP(config['host'], config['port'], timeout=15) as server:
                if config['use_tls']:
                    server.starttls()
                server.login(config['username'], config['password'])
                server.send_message(message)
    except Exception as exc:
        raise EmailCodeDeliveryError('No se pudo enviar el codigo por correo.') from exc


def preparar_registro_correo(request, user, redirect_to):
    limpiar_reto_correo(request)
    request.session[LOGIN_MFA_USER_ID_SESSION_KEY] = str(user.pk)
    request.session[LOGIN_MFA_REDIRECT_SESSION_KEY] = redirect_to


def iniciar_reto_correo(request, user, redirect_to, recipient=None, email_to_save=''):
    codigo = generar_codigo_verificacion()
    recipient = recipient or destinatario_codigo(user)
    enviar_codigo_login(codigo, user, recipient)

    request.session[LOGIN_MFA_USER_ID_SESSION_KEY] = str(user.pk)
    request.session[LOGIN_MFA_CODE_HASH_SESSION_KEY] = make_password(codigo)
    request.session[LOGIN_MFA_EXPIRES_AT_SESSION_KEY] = int(time.time()) + tiempo_vida_codigo()
    request.session[LOGIN_MFA_ATTEMPTS_SESSION_KEY] = 0
    request.session[LOGIN_MFA_EMAIL_SESSION_KEY] = mascara_correo(recipient)
    request.session[LOGIN_MFA_REDIRECT_SESSION_KEY] = redirect_to
    request.session.pop(LOGIN_MFA_EMAIL_TO_SAVE_SESSION_KEY, None)
    if email_to_save:
        request.session[LOGIN_MFA_EMAIL_TO_SAVE_SESSION_KEY] = email_to_save


def reenviar_reto_correo(request, user):
    redirect_to = request.session.get(LOGIN_MFA_REDIRECT_SESSION_KEY) or settings.LOGIN_REDIRECT_URL
    email_to_save = request.session.get(LOGIN_MFA_EMAIL_TO_SAVE_SESSION_KEY, '')
    recipient = email_to_save or (getattr(user, 'email', '') or '').strip()
    if not recipient:
        raise EmailCodeDeliveryError('No hay un correo disponible para reenviar el codigo.')

    iniciar_reto_correo(
        request,
        user,
        redirect_to,
        recipient=recipient,
        email_to_save=email_to_save,
    )


def reto_correo_expirado(request):
    try:
        expires_at = int(request.session.get(LOGIN_MFA_EXPIRES_AT_SESSION_KEY, 0))
    except (TypeError, ValueError):
        return True
    return int(time.time()) > expires_at


class CaptchaAuthenticationForm(AuthenticationForm):
    captcha = forms.CharField(
        label='Captcha de seguridad',
        strip=True,
        error_messages={
            'required': 'Resuelve el captcha para continuar.',
        },
        widget=forms.TextInput(attrs={
            'autocomplete': 'off',
            'inputmode': 'numeric',
            'pattern': '[0-9]*',
        }),
    )

    error_messages = {
        **AuthenticationForm.error_messages,
        'captcha_incorrect': 'El resultado del captcha no es correcto. Resuelve la nueva operacion.',
        'captcha_expired': 'El captcha expiro. Intenta nuevamente.',
    }

    def clean(self):
        captcha_value = (self.cleaned_data.get('captcha') or '').strip()
        expected_answer = None
        if self.request is not None:
            expected_answer = self.request.session.get(LOGIN_CAPTCHA_ANSWER_SESSION_KEY)

        if not captcha_value:
            return self.cleaned_data

        if expected_answer is None:
            self.add_error('captcha', self.error_messages['captcha_expired'])
            return self.cleaned_data

        try:
            captcha_answer = int(captcha_value)
            expected_answer = int(expected_answer)
        except (TypeError, ValueError):
            self.add_error('captcha', self.error_messages['captcha_incorrect'])
            return self.cleaned_data

        if captcha_answer != expected_answer:
            self.add_error('captcha', self.error_messages['captcha_incorrect'])
            return self.cleaned_data

        return super().clean()


class LoginCodeForm(forms.Form):
    code = forms.CharField(
        label='Codigo de verificacion',
        min_length=6,
        max_length=6,
        strip=True,
        error_messages={
            'required': 'Ingresa el codigo de verificacion.',
            'min_length': 'El codigo debe tener 6 digitos.',
            'max_length': 'El codigo debe tener 6 digitos.',
        },
        widget=forms.TextInput(attrs={
            'autocomplete': 'one-time-code',
            'inputmode': 'numeric',
            'pattern': '[0-9]*',
            'autofocus': True,
        }),
    )

    def clean_code(self):
        code = self.cleaned_data['code'].strip()
        if not code.isdigit():
            raise forms.ValidationError('El codigo debe contener solo numeros.')
        return code


class LoginEmailForm(forms.Form):
    email = forms.EmailField(
        label='Correo electronico',
        max_length=254,
        error_messages={
            'required': 'Ingresa tu correo para recibir el codigo.',
            'invalid': 'Ingresa un correo valido.',
        },
        widget=forms.EmailInput(attrs={
            'autocomplete': 'email',
            'placeholder': 'correo@ejemplo.com',
            'autofocus': True,
        }),
    )
    email_confirm = forms.EmailField(
        label='Confirmar correo',
        max_length=254,
        error_messages={
            'required': 'Confirma tu correo para continuar.',
            'invalid': 'Ingresa un correo valido para confirmar.',
        },
        widget=forms.EmailInput(attrs={
            'autocomplete': 'email',
            'placeholder': 'repite tu correo',
        }),
    )

    def clean_email(self):
        return self.cleaned_data['email'].strip().lower()

    def clean_email_confirm(self):
        return self.cleaned_data['email_confirm'].strip().lower()

    def clean(self):
        cleaned = super().clean()
        email = cleaned.get('email')
        email_confirm = cleaned.get('email_confirm')
        if email and email_confirm and email != email_confirm:
            self.add_error('email_confirm', 'Los correos no coinciden.')
        return cleaned


class CaptchaLoginView(LoginView):
    authentication_form = CaptchaAuthenticationForm
    template_name = 'login.html'
    redirect_authenticated_user = True
    login_error_message = ''

    def get(self, request, *args, **kwargs):
        limpiar_reto_correo(request)
        generar_captcha_login(request)
        return super().get(request, *args, **kwargs)

    def form_invalid(self, form):
        generar_captcha_login(self.request)
        return super().form_invalid(form)

    def form_valid(self, form):
        user = form.get_user()
        redirect_to = self.get_success_url()

        if not (user.email or '').strip():
            limpiar_captcha_login(self.request)
            preparar_registro_correo(self.request, user, redirect_to)
            return HttpResponseRedirect(reverse('login_email'))

        try:
            iniciar_reto_correo(self.request, user, redirect_to)
        except EmailCodeDeliveryError:
            self.login_error_message = (
                'No se pudo enviar el codigo de verificacion. '
                'Revisa el correo configurado e intenta de nuevo.'
            )
            return self.form_invalid(form)

        limpiar_captcha_login(self.request)
        return HttpResponseRedirect(reverse('login_code'))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        captcha_question = self.request.session.get(LOGIN_CAPTCHA_QUESTION_SESSION_KEY)
        if not captcha_question:
            captcha_question = generar_captcha_login(self.request)
        context['captcha_question'] = captcha_question
        context['login_error_message'] = self.login_error_message
        return context


@method_decorator(never_cache, name='dispatch')
class LoginEmailView(FormView):
    form_class = LoginEmailForm
    template_name = 'login_correo.html'

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return HttpResponseRedirect(settings.LOGIN_REDIRECT_URL)
        if not request.session.get(LOGIN_MFA_USER_ID_SESSION_KEY):
            return redirect('login')
        return super().dispatch(request, *args, **kwargs)

    def get_pending_user(self):
        user_id = self.request.session.get(LOGIN_MFA_USER_ID_SESSION_KEY)
        if not user_id:
            return None
        return get_user_model().objects.filter(pk=user_id, is_active=True).first()

    def form_valid(self, form):
        user = self.get_pending_user()
        if user is None:
            limpiar_reto_correo(self.request)
            return redirect('login')

        email = form.cleaned_data['email']
        redirect_to = self.request.session.get(LOGIN_MFA_REDIRECT_SESSION_KEY) or settings.LOGIN_REDIRECT_URL

        try:
            iniciar_reto_correo(
                self.request,
                user,
                redirect_to,
                recipient=email,
                email_to_save=email,
            )
        except EmailCodeDeliveryError:
            form.add_error(
                'email',
                'No se pudo enviar el codigo a ese correo. Revisa el correo e intenta de nuevo.',
            )
            return self.form_invalid(form)

        return HttpResponseRedirect(reverse('login_code'))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.get_pending_user()
        context['pending_username'] = user.get_username() if user else ''
        return context


@method_decorator(never_cache, name='dispatch')
class LoginCodeView(FormView):
    form_class = LoginCodeForm
    template_name = 'login_codigo.html'
    code_success_message = ''
    code_error_message = ''

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return HttpResponseRedirect(settings.LOGIN_REDIRECT_URL)
        if not request.session.get(LOGIN_MFA_USER_ID_SESSION_KEY):
            return redirect('login')
        if not request.session.get(LOGIN_MFA_CODE_HASH_SESSION_KEY):
            return redirect('login_email')
        return super().dispatch(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        if request.POST.get('action') == 'resend':
            return self.reenviar_codigo()
        return super().post(request, *args, **kwargs)

    def get_pending_user(self):
        user_id = self.request.session.get(LOGIN_MFA_USER_ID_SESSION_KEY)
        if not user_id:
            return None
        return get_user_model().objects.filter(pk=user_id, is_active=True).first()

    def reenviar_codigo(self):
        user = self.get_pending_user()
        if user is None:
            limpiar_reto_correo(self.request)
            return redirect('login')

        try:
            reenviar_reto_correo(self.request, user)
        except EmailCodeDeliveryError:
            self.code_error_message = (
                'No se pudo reenviar el codigo. Verifica el correo e intenta de nuevo.'
            )
        else:
            self.code_success_message = (
                'Te enviamos un nuevo codigo. Usa el ultimo que recibas.'
            )

        return self.render_to_response(self.get_context_data(form=self.form_class()))

    def form_valid(self, form):
        if reto_correo_expirado(self.request):
            limpiar_reto_correo(self.request)
            form.add_error('code', 'El codigo expiro. Vuelve a iniciar sesion.')
            return self.form_invalid(form)

        expected_hash = self.request.session.get(LOGIN_MFA_CODE_HASH_SESSION_KEY)
        if not expected_hash or not check_password(form.cleaned_data['code'], expected_hash):
            attempts = int(self.request.session.get(LOGIN_MFA_ATTEMPTS_SESSION_KEY, 0)) + 1
            self.request.session[LOGIN_MFA_ATTEMPTS_SESSION_KEY] = attempts
            remaining = max_intentos_codigo() - attempts

            if remaining <= 0:
                limpiar_reto_correo(self.request)
                form.add_error('code', 'Demasiados intentos. Vuelve a iniciar sesion.')
            else:
                form.add_error('code', f'Codigo incorrecto. Te quedan {remaining} intento(s).')
            return self.form_invalid(form)

        user = self.get_pending_user()
        if user is None:
            limpiar_reto_correo(self.request)
            return redirect('login')

        email_to_save = self.request.session.get(LOGIN_MFA_EMAIL_TO_SAVE_SESSION_KEY, '')
        if email_to_save and user.email != email_to_save:
            user.email = email_to_save
            user.save(update_fields=['email'])

        redirect_to = self.request.session.get(LOGIN_MFA_REDIRECT_SESSION_KEY) or settings.LOGIN_REDIRECT_URL
        limpiar_reto_correo(self.request)
        auth_login(self.request, user)
        return HttpResponseRedirect(redirect_to)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['masked_email'] = self.request.session.get(LOGIN_MFA_EMAIL_SESSION_KEY, '')
        context['code_success_message'] = self.code_success_message
        context['code_error_message'] = self.code_error_message
        return context
