VIEWY.PYfrom django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.db.models import Count, Q, Sum, F
from django.http import HttpResponse
import csv
from .models import Booking
from django import forms
from decimal import Decimal
from django.contrib.auth.forms import AuthenticationForm
from datetime import date, timedelta
from django.contrib.auth.models import User

# دالة للتحقق من أن المستخدم لديه صلاحيات Team Leader أو Superuser
def is_team_leader(user):
    """
    تتحقق مما إذا كان المستخدم لديه صلاحيات مدير فريق أو مشرف عام.
    """
    return user.is_staff or user.is_superuser

# دالة للتحقق من أن المستخدم لديه صلاحيات Superuser
def is_super(user):
    """
    تتحقق مما إذا كان المستخدم لديه صلاحيات مشرف عام.
    """
    return user.is_superuser

# تعريف الخيارات للحقول الجديدة
BOOKING_TYPE_CHOICES = [
    ('new', 'جديد'),
    ('installment', 'تقسيط'),
    ('edit', 'تعديل'),
    ('cancel', 'إلغاء'),
]

SERVICE_TYPE_CHOICES = [
    ('flight', 'طيران'),
    ('hotel', 'فندق'),
    ('delivery', 'توصيل'),
    ('visa', 'فيزا'),
]

BOOKING_METHOD_CHOICES = [
    ('whatsapp', 'واتساب'),
    ('call', 'مكالمة'),
    ('old_client', 'عميل قديم'),
]

SERVICE_PROVIDER_CHOICES = [
    ('smile', 'سمايل'),
    ('amadeus', 'أماديوس'),
    ('other', 'غيره'),
]

PAYMENT_METHOD_CHOICES = [
    ('link', 'رابط سداد'),
    ('bank_transfer', 'تحويل بنكي'),
    ('cash', 'كاش'),
]

CURRENCY_CHOICES = [
    ('kwd', 'KWD'),
    ('sar', 'SAR'),
    ('aed', 'AED'),
]

# نموذج لإضافة حجز جديد مع جميع الحقول
class BookingForm(forms.ModelForm):
    """
    نموذج Django لإضافة وتعديل الحجوزات.
    """
    booking_number = forms.CharField(max_length=50, label='رقم الحجز', required=True)
    booking_type = forms.ChoiceField(choices=BOOKING_TYPE_CHOICES, label='نوع الحجز', required=True)
    nationality = forms.CharField(max_length=100, label='الجنسية', required=True)
    booking_method = forms.ChoiceField(choices=BOOKING_METHOD_CHOICES, label='طريقة الحجز', required=True)
    service_provider = forms.ChoiceField(choices=SERVICE_PROVIDER_CHOICES, label='الوكيل', required=True)
    check_in_date = forms.DateField(label='تاريخ الدخول', widget=forms.DateInput(attrs={'type': 'date'}))
    net_price = forms.DecimalField(label='السعر نت', max_digits=10, decimal_places=2, required=True)
    selling_price = forms.DecimalField(label='سعر البيع', max_digits=10, decimal_places=2, required=True)
    amount_paid = forms.DecimalField(label='المبلغ المدفوع', max_digits=10, decimal_places=2, required=True)
    last_payment_date = forms.DateField(label='آخر يوم للسداد', required=False, widget=forms.DateInput(attrs={'type': 'date'}))
    payment_method = forms.ChoiceField(choices=PAYMENT_METHOD_CHOICES, label='طريقة السداد', required=True)
    currency = forms.ChoiceField(choices=CURRENCY_CHOICES, label='الدفع (العملة)', required=True)
    notes = forms.CharField(label='ملاحظات', widget=forms.Textarea, required=False)

    class Meta:
        model = Booking
        fields = [
            'booking_number', 'booking_type', 'customer_name', 'phone_number', 'email', 'nationality', 'booking_method',
            'service_type', 'service_provider', 'booking_date', 'check_in_date',
            'net_price', 'selling_price', 'amount_paid', 'last_payment_date', 'payment_method', 'currency', 'notes'
        ]

# نموذج لتسجيل دخول المستخدم
class LoginForm(forms.Form):
    """
    نموذج بسيط لتسجيل دخول المستخدم.
    """
    username = forms.CharField(max_length=150)
    password = forms.CharField(widget=forms.PasswordInput)

def agent_login(request):
    """
    تُعالج عملية تسجيل دخول الوكلاء.
    """
    if request.method == 'POST':
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            username = form.cleaned_data.get('username')
            password = form.cleaned_data.get('password')
            user = authenticate(request, username=username, password=password)
            if user is not None:
                login(request, user)
                if user.is_superuser:
                    return redirect('super_dashboard')
                elif user.is_staff:
                    return redirect('team_leader_dashboard')
                else:
                    return redirect('agent_dashboard')
            else:
                messages.error(request, 'Invalid username or password.')
    else:
        form = LoginForm()
    
    return render(request, 'sales/login.html', {'form': form})

@login_required
def agent_dashboard(request):
    """
    تعرض لوحة التحكم الخاصة بالوكيل مع إحصائيات حجوزاته.
    """
    agent_bookings = Booking.objects.filter(agent=request.user)

    # Calculate summary statistics with an alias for profit
    summary_data = agent_bookings.aggregate(
        total_profit=Sum(F('selling_price') - F('net_price')),
        total_paid=Sum('amount_paid'),
        total_selling_price=Sum('selling_price')
    )

    total_profit = summary_data['total_profit'] or Decimal('0.00')
    total_paid = summary_data['total_paid'] or Decimal('0.00')
    total_selling_price = summary_data['total_selling_price'] or Decimal('0.00')
    total_remaining = total_selling_price - total_paid
    total_bookings = agent_bookings.count()
    
    # Logic to get upcoming payments
    today = date.today()
    one_week_later = today + timedelta(days=7)

    # Filter for bookings with remaining balance and a payment date
    upcoming_payments = agent_bookings.filter(
        selling_price__gt=F('amount_paid'),
        last_payment_date__isnull=False
    ).order_by('last_payment_date')
    
    for payment in upcoming_payments:
        if payment.last_payment_date <= today:
            payment.reminder_color = 'red'  # Due or overdue
        elif payment.last_payment_date <= one_week_later:
            payment.reminder_color = 'yellow' # Due within a week
        else:
            payment.reminder_color = 'green' # Not due soon

    context = {
        'bookings': agent_bookings,
        'total_profit': total_profit,
        'total_paid': total_paid,
        'total_remaining': total_remaining,
        'total_bookings': total_bookings,
        'upcoming_payments': upcoming_payments, # Pass the new list to the template
    }
    return render(request, 'sales/agent_dashboard.html', context)

@login_required
def add_booking(request):
    """
    تُعالج عملية إضافة حجز جديد.
    """
    if request.method == 'POST':
        form = BookingForm(request.POST)
        if form.is_valid():
            new_booking = form.save(commit=False)
            
            net_price = form.cleaned_data.get('net_price')
            selling_price = form.cleaned_data.get('selling_price')
            new_booking.profit = selling_price - net_price
            
            new_booking.agent = request.user
            new_booking.save()
            messages.success(request, 'Booking added successfully!')
            
            action = request.POST.get('action')
            if action == 'save_and_new':
                return redirect('add_booking')
            else:
                return redirect('agent_dashboard')
    else:
        form = BookingForm()
    
    context = {'form': form}
    return render(request, 'sales/add_booking.html', context)

@login_required
def edit_booking(request, booking_id):
    """
    تُعالج عملية تعديل حجز خاص بالوكيل.
    """
    booking = get_object_or_404(Booking, id=booking_id, agent=request.user)
    
    if request.method == 'POST':
        form = BookingForm(request.POST, instance=booking)
        if form.is_valid():
            edited_booking = form.save(commit=False)
            
            net_price = form.cleaned_data.get('net_price')
            selling_price = form.cleaned_data.get('selling_price')
            edited_booking.profit = selling_price - net_price
            
            edited_booking.save()
            messages.success(request, 'Booking updated successfully!')
            return redirect('agent_dashboard')
    else:
        form = BookingForm(instance=booking)
    
    context = {'form': form, 'booking': booking}
    return render(request, 'sales/edit_booking.html', context)

@login_required
def delete_booking(request, booking_id):
    """
    تُعالج عملية حذف حجز خاص بالوكيل.
    """
    booking = get_object_or_404(Booking, id=booking_id, agent=request.user)
    
    if request.method == 'POST':
        booking.delete()
        messages.success(request, 'Booking deleted successfully!')
        return redirect('agent_dashboard')
        
    context = {'booking': booking}
    return render(request, 'sales/delete_booking.html', context)

@user_passes_test(is_team_leader)
def team_leader_dashboard(request):
    """
    لوحة تحكم مدير الفريق، تعرض جميع الحجوزات مع خاصية البحث.
    """
    query = request.GET.get('q')
    bookings = Booking.objects.all().order_by('-created_at')
    
    if query:
        bookings = bookings.filter(
            Q(customer_name__icontains=query) |
            Q(service_type__icontains=query)
        )
    
    return render(request, 'sales/team_leader_dashboard.html', {'bookings': bookings})

@user_passes_test(is_super)
def super_dashboard(request):
    """
    لوحة تحكم المشرف العام، تعرض جميع الحجوزات مع خاصية البحث.
    """
    query = request.GET.get('q')
    bookings = Booking.objects.all().order_by('-created_at')
    
    if query:
        bookings = bookings.filter(
            Q(customer_name__icontains=query) |
            Q(service_type__icontains=query)
        )
    
    return render(request, 'sales/super_dashboard.html', {'bookings': bookings})

@user_passes_test(is_team_leader)
def edit_booking_tl_super(request, booking_id):
    """
    تُعالج عملية تعديل الحجوزات من قبل مدير الفريق أو المشرف العام.
    """
    booking = get_object_or_404(Booking, id=booking_id)
    if request.method == 'POST':
        form = BookingForm(request.POST, instance=booking)
        if form.is_valid():
            edited_booking = form.save(commit=False)
            
            net_price = form.cleaned_data.get('net_price')
            selling_price = form.cleaned_data.get('selling_price')
            edited_booking.profit = selling_price - net_price
            
            edited_booking.save()
            messages.success(request, 'تم تعديل الحجز بنجاح!')
            return redirect('team_leader_dashboard')
    else:
        form = BookingForm(instance=booking)
    return render(request, 'sales/edit_booking.html', {'form': form, 'booking': booking})

@user_passes_test(is_team_leader)
def delete_booking_tl_super(request, booking_id):
    """
    تُعالج عملية حذف الحجوزات من قبل مدير الفريق أو المشرف العام.
    """
    booking = get_object_or_404(Booking, id=booking_id)
    if request.method == 'POST':
        booking.delete()
        messages.success(request, 'تم حذف الحجز بنجاح!')
        return redirect('team_leader_dashboard')
    return render(request, 'sales/delete_booking.html', {'booking': booking})

@user_passes_test(is_team_leader)
def analytics_dashboard(request):
    """
    تعرض لوحة تحكم التحليلات مع إحصائيات شاملة للحجوزات.
    """
    # إحصائيات عامة
    total_bookings = Booking.objects.count()
    overall_stats = Booking.objects.aggregate(
        total_profit=Sum(F('selling_price') - F('net_price')),
        total_selling_price=Sum('selling_price'),
        total_paid=Sum('amount_paid')
    )

    # الإحصائيات حسب الموظف
    agent_stats = Booking.objects.values('agent__username').annotate(
        count=Count('id'),
        total_profit=Sum(F('selling_price') - F('net_price')),
        total_selling_price=Sum('selling_price'),
        total_paid=Sum('amount_paid')
    ).order_by('-total_profit')
    
    # الإحصائيات حسب نوع الخدمة
    bookings_by_service = Booking.objects.values('service_type').annotate(count=Count('id')).order_by('-count')

    context = {
        'total_bookings': total_bookings,
        'overall_stats': overall_stats,
        'agent_stats': list(agent_stats),
        'bookings_by_service': list(bookings_by_service),
    }
    return render(request, 'sales/analytics_dashboard.html', context)
    
@user_passes_test(is_team_leader)
def export_bookings_csv(request):
    """
    تُصدّر بيانات الحجوزات إلى ملف CSV.
    """
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="bookings_report.csv"'

    writer = csv.writer(response)
    writer.writerow(['Customer Name', 'Service Type', 'Booking Date', 'Agent'])

    bookings = Booking.objects.all().values_list('customer_name', 'service_type', 'booking_date', 'agent__username')
    for booking in bookings:
        writer.writerow(booking)

    return response
===================
URLS.PYfrom django.urls import path
from . import views
from django.contrib.auth import views as auth_views

urlpatterns = [
    path('', views.agent_login, name='agent_login'),
    path('dashboard/', views.agent_dashboard, name='agent_dashboard'),
    path('dashboard/add/', views.add_booking, name='add_booking'),
    path('dashboard/edit/<int:booking_id>/', views.edit_booking, name='edit_booking'),
    # تم إزالة مسار الحذف من لوحة تحكم الوكيل بناءً على طلبك
    path('logout/', auth_views.LogoutView.as_view(template_name='sales/logged_out.html'), name='agent_logout'),
    path('team-leader-dashboard/', views.team_leader_dashboard, name='team_leader_dashboard'),
    path('super-dashboard/', views.super_dashboard, name='super_dashboard'),
    path('edit/<int:booking_id>/', views.edit_booking_tl_super, name='edit_booking_tl_super'),
    path('delete/<int:booking_id>/', views.delete_booking_tl_super, name='delete_booking_tl_super'),
    path('analytics/', views.analytics_dashboard, name='analytics_dashboard'),
    path('export/csv/', views.export_bookings_csv, name='export_bookings_csv'),
]
==============
MODELS.PYfrom django.db import models
from django.contrib.auth.models import User
from decimal import Decimal

class Booking(models.Model):
    agent = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    booking_number = models.CharField(max_length=255, default='0')
    booking_type = models.CharField(max_length=50, default='new')
    booking_date = models.DateField()
    customer_name = models.CharField(max_length=255)
    phone_number = models.CharField(max_length=20, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    nationality = models.CharField(max_length=100, default='unknown')
    booking_method = models.CharField(max_length=50, default='unknown')
    service_type = models.CharField(max_length=50, default='unknown')
    service_provider = models.CharField(max_length=50, default='unknown')
    check_in_date = models.DateField(blank=True, null=True)
    net_price = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    selling_price = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    profit = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    amount_paid = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    currency = models.CharField(max_length=10, default='KWD')
    payment_method = models.CharField(max_length=50, default='unknown')
    last_payment_date = models.DateField(blank=True, null=True)
    notes = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f'{self.customer_name} - {self.booking_number}'
===============
APPS.PYfrom django.apps import AppConfig


class SalesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'sales'
==================
ADD_BOOKING.HTML<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>إضافة حجز جديد</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0-beta3/css/all.min.css" rel="stylesheet">
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Tajawal:wght@400;700&display=swap');
        body {
            font-family: 'Tajawal', sans-serif;
        }
        .container-grid {
            display: grid;
            grid-template-columns: 1fr;
            gap: 2rem;
        }
        @media (min-width: 1024px) {
            .container-grid {
                grid-template-columns: 1fr 4fr;
            }
        }
    </style>
</head>
<body class="bg-gray-100 font-sans leading-normal tracking-normal text-right">
    <div class="min-h-screen flex flex-col lg:flex-row">
        <!-- Sidebar Navigation -->
        <aside class="w-full lg:w-64 bg-white p-6 shadow-xl rounded-b-lg lg:rounded-l-lg lg:rounded-r-none mb-6 lg:mb-0 lg:mr-6">
            <h1 class="text-2xl font-bold text-gray-800 mb-6">نظام الحجوزات</h1>
            <nav class="space-y-4">
                <a href="{% url 'agent_dashboard' %}" class="flex items-center px-4 py-2 text-gray-700 hover:bg-gray-200 rounded-lg transition-colors duration-200">
                    <i class="fas fa-home ml-3"></i> لوحة التحكم
                </a>
                <a href="{% url 'add_booking' %}" class="flex items-center px-4 py-2 bg-indigo-600 text-white rounded-lg transition-colors duration-200">
                    <i class="fas fa-plus-circle ml-3"></i> إضافة حجز جديد
                </a>
                <a href="{% url 'analytics_dashboard' %}" class="flex items-center px-4 py-2 text-gray-700 hover:bg-gray-200 rounded-lg transition-colors duration-200">
                    <i class="fas fa-chart-pie ml-3"></i> التقارير
                </a>
                <a href="{% url 'admin:logout' %}" class="flex items-center px-4 py-2 text-red-600 hover:bg-red-100 rounded-lg transition-colors duration-200 mt-8">
                    <i class="fas fa-sign-out-alt ml-3"></i> تسجيل الخروج
                </a>
            </nav>
        </aside>

        <!-- Main Content -->
        <main class="flex-1 p-4 md:p-8 bg-gray-100">
            <h1 class="text-3xl md:text-4xl font-bold text-gray-800 mb-6">نموذج إضافة حجز</h1>
            
            <form method="post" class="bg-white p-6 md:p-10 rounded-lg shadow-xl" id="bookingForm">
                {% csrf_token %}
                
                <!-- تفاصيل الحجز -->
                <div class="mb-8 p-6 bg-gray-50 rounded-lg border border-gray-200">
                    <h2 class="text-2xl font-semibold text-gray-700 mb-4">1. تفاصيل الحجز</h2>
                    <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
                        <div>
                            <label for="id_booking_number" class="block text-gray-700 font-medium mb-1">رقم الحجز</label>
                            <input type="text" name="booking_number" id="id_booking_number" required class="w-full p-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-600 transition duration-200">
                        </div>
                        <div>
                            <label for="id_booking_type" class="block text-gray-700 font-medium mb-1">نوع الحجز</label>
                            <select name="booking_type" id="id_booking_type" class="w-full p-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-600 transition duration-200">
                                <option value="new">جديد</option>
                                <option value="installment">تقسيط</option>
                                <option value="edit">تعديل</option>
                                <option value="cancel">إلغاء</option>
                            </select>
                        </div>
                        <div>
                            <label for="id_booking_date" class="block text-gray-700 font-medium mb-1">تاريخ الحجز</label>
                            <input type="date" name="booking_date" id="id_booking_date" required class="w-full p-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-600 transition duration-200">
                        </div>
                    </div>
                </div>

                <!-- بيانات العميل -->
                <div class="mb-8 p-6 bg-gray-50 rounded-lg border border-gray-200">
                    <h2 class="text-2xl font-semibold text-gray-700 mb-4">2. بيانات العميل</h2>
                    <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
                        <div>
                            <label for="id_customer_name" class="block text-gray-700 font-medium mb-1">الاسم</label>
                            <input type="text" name="customer_name" id="id_customer_name" required class="w-full p-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-600 transition duration-200">
                        </div>
                        <div>
                            <label for="id_phone_number" class="block text-gray-700 font-medium mb-1">رقم التليفون</label>
                            <input type="text" name="phone_number" id="id_phone_number" class="w-full p-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-600 transition duration-200">
                        </div>
                        <div>
                            <label for="id_email" class="block text-gray-700 font-medium mb-1">البريد الإلكتروني</label>
                            <input type="email" name="email" id="id_email" class="w-full p-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-600 transition duration-200">
                        </div>
                        <div>
                            <label for="id_nationality" class="block text-gray-700 font-medium mb-1">الجنسية</label>
                            <input type="text" name="nationality" id="id_nationality" required class="w-full p-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-600 transition duration-200">
                        </div>
                        <div>
                            <label for="id_booking_method" class="block text-gray-700 font-medium mb-1">طريقة الحجز</label>
                            <select name="booking_method" id="id_booking_method" class="w-full p-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-600 transition duration-200">
                                <option value="whatsapp">واتساب</option>
                                <option value="call">مكالمة</option>
                                <option value="old_client">عميل قديم</option>
                            </select>
                        </div>
                    </div>
                </div>

                <!-- تفاصيل الحجز -->
                <div class="mb-8 p-6 bg-gray-50 rounded-lg border border-gray-200">
                    <h2 class="text-2xl font-semibold text-gray-700 mb-4">3. تفاصيل الخدمة</h2>
                    <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
                        <div>
                            <label for="id_service_type" class="block text-gray-700 font-medium mb-1">نوع الخدمة</label>
                            <select name="service_type" id="id_service_type" class="w-full p-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-600 transition duration-200">
                                <option value="flight">طيران</option>
                                <option value="hotel">فندق</option>
                                <option value="delivery">توصيل</option>
                                <option value="visa">فيزا</option>
                            </select>
                        </div>
                        <div>
                            <label for="id_service_provider" class="block text-gray-700 font-medium mb-1">الوكيل</label>
                            <select name="service_provider" id="id_service_provider" class="w-full p-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-600 transition duration-200">
                                <option value="smile">سمايل</option>
                                <option value="amadeus">أماديوس</option>
                                <option value="other">غيره</option>
                            </select>
                        </div>
                        <div>
                            <label for="id_check_in_date" class="block text-gray-700 font-medium mb-1">تاريخ الدخول</label>
                            <input type="date" name="check_in_date" id="id_check_in_date" required class="w-full p-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-600 transition duration-200">
                        </div>
                    </div>
                </div>

                <!-- تفاصيل الدفع -->
                <div class="mb-8 p-6 bg-gray-50 rounded-lg border border-gray-200">
                    <h2 class="text-2xl font-semibold text-gray-700 mb-4">4. تفاصيل الدفع</h2>
                    <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
                        <div>
                            <label for="id_net_price" class="block text-gray-700 font-medium mb-1">السعر نت</label>
                            <input type="number" step="0.01" name="net_price" id="id_net_price" required class="w-full p-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-600 transition duration-200">
                        </div>
                        <div>
                            <label for="id_selling_price" class="block text-gray-700 font-medium mb-1">سعر البيع</label>
                            <input type="number" step="0.01" name="selling_price" id="id_selling_price" required class="w-full p-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-600 transition duration-200">
                        </div>
                        <div>
                            <label for="id_amount_paid" class="block text-gray-700 font-medium mb-1">المبلغ المدفوع</label>
                            <input type="number" step="0.01" name="amount_paid" id="id_amount_paid" required class="w-full p-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-600 transition duration-200">
                            <div id="payment-status" class="mt-2 text-sm"></div>
                        </div>
                        <div>
                            <label for="profit-amount" class="block text-gray-700 font-medium mb-1">الربح</label>
                            <input type="text" id="profit-amount" readonly class="w-full p-3 bg-gray-200 border border-gray-300 rounded-lg">
                        </div>
                        <div>
                            <label for="id_currency" class="block text-gray-700 font-medium mb-1">الدفع (العملة)</label>
                            <select name="currency" id="id_currency" class="w-full p-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-600 transition duration-200">
                                <option value="kwd">KWD</option>
                                <option value="sar">SAR</option>
                                <option value="aed">AED</option>
                            </select>
                        </div>
                        <div>
                            <label for="id_payment_method" class="block text-gray-700 font-medium mb-1">طريقة السداد</label>
                            <select name="payment_method" id="id_payment_method" required class="w-full p-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-600 transition duration-200">
                                <option value="link">رابط سداد</option>
                                <option value="bank_transfer">تحويل بنكي</option>
                                <option value="cash">كاش</option>
                            </select>
                        </div>
                        <div id="remaining-amount-container" class="hidden">
                            <label for="remaining-amount" class="block text-gray-700 font-medium mb-1">المبلغ المتبقي</label>
                            <input type="text" id="remaining-amount" readonly class="w-full p-3 bg-gray-200 border border-gray-300 rounded-lg">
                        </div>
                        <div id="last-payment-date-container" class="hidden">
                            <label for="id_last_payment_date" class="block text-gray-700 font-medium mb-1">آخر يوم للسداد</label>
                            <input type="date" name="last_payment_date" id="id_last_payment_date" class="w-full p-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-600 transition duration-200">
                        </div>
                        <div id="file-upload-container" class="hidden">
                            <label for="file-upload" class="block text-gray-700 font-medium mb-1">إرفاق ملف</label>
                            <input type="file" id="file-upload" class="w-full p-3 border border-gray-300 rounded-lg">
                        </div>
                        <div id="link-upload-container" class="hidden">
                            <label for="link-upload" class="block text-gray-700 font-medium mb-1">رابط السداد</label>
                            <input type="url" id="link-upload" class="w-full p-3 border border-gray-300 rounded-lg">
                        </div>
                    </div>
                </div>

                <!-- إرفاق المستندات والملاحظات -->
                <div class="mb-8 p-6 bg-gray-50 rounded-lg border border-gray-200">
                    <h2 class="text-2xl font-semibold text-gray-700 mb-4">5. المستندات والملاحظات</h2>
                    <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
                        <div>
                            <label for="voucher_file" class="block text-gray-700 font-medium mb-1">إرفاق الفاوتشر</label>
                            <input type="file" name="voucher_file" id="voucher_file" class="w-full p-3 border border-gray-300 rounded-lg">
                        </div>
                        <div>
                            <label for="invoice_file" class="block text-gray-700 font-medium mb-1">إرفاق الفاتورة</label>
                            <input type="file" name="invoice_file" id="invoice_file" class="w-full p-3 border border-gray-300 rounded-lg">
                        </div>
                        <div class="md:col-span-2">
                            <label for="id_notes" class="block text-gray-700 font-medium mb-1">ملاحظات</label>
                            <textarea name="notes" id="id_notes" rows="4" class="w-full p-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-600 transition duration-200"></textarea>
                        </div>
                    </div>
                </div>

                <!-- أزرار الإرسال -->
                <div class="flex flex-col md:flex-row gap-4 justify-center">
                    <button type="submit" name="action" value="save_and_return" class="px-6 py-3 bg-indigo-600 text-white rounded-lg shadow-md hover:bg-indigo-700 transition duration-300">
                        حفظ والعودة للصفحة الرئيسية
                    </button>
                    <button type="submit" name="action" value="save_and_new" class="px-6 py-3 bg-gray-800 text-white rounded-lg shadow-md hover:bg-gray-900 transition duration-300">
                        حفظ وعمل حجز جديد
                    </button>
                </div>
            </form>
        </main>
    </div>
    
    <script>
        const amountPaidInput = document.getElementById('id_amount_paid');
        const sellingPriceInput = document.getElementById('id_selling_price');
        const netPriceInput = document.getElementById('id_net_price');
        const paymentStatusDiv = document.getElementById('payment-status');
        const bookingTypeSelect = document.getElementById('id_booking_type');
        const lastPaymentDateContainer = document.getElementById('last-payment-date-container');
        const remainingAmountContainer = document.getElementById('remaining-amount-container');
        const paymentMethodSelect = document.getElementById('id_payment_method');
        const fileUploadContainer = document.getElementById('file-upload-container');
        const linkUploadContainer = document.getElementById('link-upload-container');
        const remainingAmountInput = document.getElementById('remaining-amount');
        const profitInput = document.getElementById('profit-amount');


        function updatePaymentStatus() {
            const amountPaid = parseFloat(amountPaidInput.value) || 0;
            const sellingPrice = parseFloat(sellingPriceInput.value) || 0;
            const netPrice = parseFloat(netPriceInput.value) || 0;

            // Calculate profit
            const profit = (sellingPrice - netPrice).toFixed(2);
            profitInput.value = profit;
            
            paymentStatusDiv.textContent = '';
            paymentStatusDiv.classList.remove('text-red-500', 'text-green-500', 'text-yellow-500');
            
            if (sellingPrice > 0 && amountPaid > sellingPrice) {
                paymentStatusDiv.textContent = 'تحذير: المبلغ المدفوع أكبر من سعر البيع!';
                paymentStatusDiv.classList.add('text-red-500');
            } else if (sellingPrice > 0 && amountPaid < sellingPrice) {
                const remaining = (sellingPrice - amountPaid).toFixed(2);
                paymentStatusDiv.textContent = 'المبلغ المتبقي هو ' + remaining;
                paymentStatusDiv.classList.add('text-yellow-500');
                remainingAmountInput.value = remaining;
                
            } else if (sellingPrice > 0 && amountPaid === sellingPrice) {
                paymentStatusDiv.textContent = 'تم دفع المبلغ بالكامل.';
                paymentStatusDiv.classList.add('text-green-500');
            }
        }

        function toggleInstallmentFields() {
            const amountPaid = parseFloat(amountPaidInput.value) || 0;
            const sellingPrice = parseFloat(sellingPriceInput.value) || 0;
            const isInstallmentNeeded = (sellingPrice > 0 && amountPaid < sellingPrice);

            remainingAmountContainer.classList.toggle('hidden', !isInstallmentNeeded);
            lastPaymentDateContainer.classList.toggle('hidden', !isInstallmentNeeded);
        }

        function updatePaymentMethodFields() {
            const paymentMethod = paymentMethodSelect.value;
            if (paymentMethod === 'link') {
                linkUploadContainer.classList.remove('hidden');
                fileUploadContainer.classList.add('hidden');
            } else {
                fileUploadContainer.classList.remove('hidden');
                linkUploadContainer.classList.add('hidden');
            }
        }

        // Add event listeners
        amountPaidInput.addEventListener('input', () => {
            updatePaymentStatus();
            toggleInstallmentFields();
        });
        sellingPriceInput.addEventListener('input', () => {
            updatePaymentStatus();
            toggleInstallmentFields();
        });
        netPriceInput.addEventListener('input', updatePaymentStatus);
        paymentMethodSelect.addEventListener('change', updatePaymentMethodFields);

        // Initial check on page load
        document.addEventListener('DOMContentLoaded', () => {
            updatePaymentStatus();
            toggleInstallmentFields();
            updatePaymentMethodFields();
        });

        // Handle form submission logic for two buttons
        document.getElementById('bookingForm').addEventListener('submit', function(event) {
            const form = event.target;
            const action = event.submitter.value;

            // Prevent default form submission
            event.preventDefault();

            // Set a hidden input to indicate which button was clicked
            const hiddenInput = document.createElement('input');
            hiddenInput.type = 'hidden';
            hiddenInput.name = 'action_type';
            hiddenInput.value = action;
            form.appendChild(hiddenInput);

            // Re-submit the form
            form.submit();
        });
    </script>
</body>
</html>
===================
AGENT_DASHBOARD.HTML{% load sales_filters %}
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>لوحة تحكم الوكيل</title>
    <!-- Tailwind CSS CDN -->
    <script src="https://cdn.tailwindcss.com"></script>
    <!-- Bootstrap Icons for a modern look -->
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.min.css">
    <!-- Font Awesome for icons -->
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0-beta3/css/all.min.css">
    <!-- Custom styles for gradients -->
    <style>
        .bg-gradient-primary {
            background: linear-gradient(45deg, #0d6efd, #054ea3);
        }
        .bg-gradient-success {
            background: linear-gradient(45deg, #28a745, #1d6e35);
        }
        .bg-gradient-warning {
            background: linear-gradient(45deg, #ffc107, #d4a700);
        }
        .bg-gradient-danger {
            background: linear-gradient(45deg, #dc3545, #a30e1d);
        }
    </style>
</head>
<body class="bg-gray-100 font-sans">

    <div class="flex flex-col md:flex-row min-h-screen">
        <!-- Sidebar -->
        <div class="md:w-64 bg-white shadow-lg md:fixed md:top-0 md:right-0 md:h-screen md:flex md:flex-col p-4 z-50">
            <div class="flex flex-col items-center justify-center md:items-start md:justify-start">
                <a href="#" class="flex items-center pb-3 text-gray-800 text-decoration-none">
                    <span class="text-xl font-bold">نظام الحجوزات</span>
                </a>
                <hr class="w-full my-2 border-gray-300">
                <ul class="flex flex-col w-full text-right mt-4">
                    <li class="w-full mb-2">
                        <a href="{% url 'agent_dashboard' %}" class="nav-link p-2 rounded-md transition duration-300 hover:bg-gray-200 flex items-center text-gray-800 bg-blue-100">
                            <i class="fs-4 bi-house-door"></i>
                            <span class="ms-2">لوحة التحكم</span>
                        </a>
                    </li>
                    <li class="w-full mb-2">
                        <a href="{% url 'add_booking' %}" class="nav-link p-2 rounded-md transition duration-300 hover:bg-gray-200 flex items-center text-gray-800">
                            <i class="fs-4 bi-plus-circle"></i>
                            <span class="ms-2">إضافة حجز جديد</span>
                        </a>
                    </li>
                    <li class="w-full mb-2">
                        <a href="{% url 'analytics_dashboard' %}" class="nav-link p-2 rounded-md transition duration-300 hover:bg-gray-200 flex items-center text-gray-800">
                            <i class="fs-4 bi-journal-text"></i>
                            <span class="ms-2">التقارير</span>
                        </a>
                    </li>
                    <li class="w-full mt-auto mb-2 md:mt-16">
                        <a href="{% url 'agent_logout' %}" class="nav-link p-2 rounded-md transition duration-300 hover:bg-red-100 flex items-center text-red-500">
                            <i class="fs-4 bi-box-arrow-right"></i>
                            <span class="ms-2">تسجيل الخروج</span>
                        </a>
                    </li>
                </ul>
            </div>
        </div>

        <!-- Main Content -->
        <main class="flex-grow md:mr-64 p-4 md:p-8">
            <h1 class="text-3xl font-bold mb-6 text-gray-800 text-right">لوحة تحكم الوكيل</h1>

            {% if messages %}
            <div class="bg-green-100 text-green-700 p-4 rounded-lg mb-4 text-center">
                {% for message in messages %}
                    {{ message }}
                {% endfor %}
            </div>
            {% endif %}

            <!-- Info Cards Section -->
            <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
                <!-- Card 1: Total Profit -->
                <div class="info-card bg-gradient-primary rounded-xl p-6 relative overflow-hidden shadow-lg transition-transform hover:translate-y-[-8px]">
                    <span class="absolute bottom-[-15px] left-[-15px] text-white opacity-10 text-7xl leading-none">
                        <i class="bi bi-currency-dollar"></i>
                    </span>
                    <div class="text-white text-4xl font-bold mb-2">{{ total_profit }}</div>
                    <div class="text-white text-sm opacity-90">إجمالي الربح</div>
                </div>

                <!-- Card 2: Total Sales -->
                <div class="info-card bg-gradient-success rounded-xl p-6 relative overflow-hidden shadow-lg transition-transform hover:translate-y-[-8px]">
                    <span class="absolute bottom-[-15px] left-[-15px] text-white opacity-10 text-7xl leading-none">
                        <i class="bi bi-cash-stack"></i>
                    </span>
                    <div class="text-white text-4xl font-bold mb-2">{{ total_paid }}</div>
                    <div class="text-white text-sm opacity-90">إجمالي المدفوع</div>
                </div>

                <!-- Card 3: Total Paid -->
                <div class="info-card bg-gradient-warning rounded-xl p-6 relative overflow-hidden shadow-lg transition-transform hover:translate-y-[-8px]">
                    <span class="absolute bottom-[-15px] left-[-15px] text-white opacity-10 text-7xl leading-none">
                        <i class="bi bi-check2-circle"></i>
                    </span>
                    <div class="text-white text-4xl font-bold mb-2">{{ total_bookings }}</div>
                    <div class="text-white text-sm opacity-90">إجمالي الحجوزات</div>
                </div>

                <!-- Card 4: Total Remaining -->
                <div class="info-card bg-gradient-danger rounded-xl p-6 relative overflow-hidden shadow-lg transition-transform hover:translate-y-[-8px]">
                    <span class="absolute bottom-[-15px] left-[-15px] text-white opacity-10 text-7xl leading-none">
                        <i class="bi bi-x-circle"></i>
                    </span>
                    <div class="text-white text-4xl font-bold mb-2">{{ total_remaining }}</div>
                    <div class="text-white text-sm opacity-90">إجمالي المتبقي</div>
                </div>
            </div>

            <!-- Upcoming Payments Section -->
            <div class="bg-white rounded-xl shadow-lg p-6 mb-8">
                <div class="flex items-center justify-between border-b pb-4 mb-4">
                    <h2 class="text-xl font-semibold text-gray-800"><i class="bi bi-bell-fill text-yellow-500 ml-2"></i> تذكير بالدفعات القادمة</h2>
                    <a href="#" class="text-blue-600 hover:underline">عرض الكل</a>
                </div>
                <ul id="upcomingPaymentsList" class="divide-y divide-gray-200 text-right">
                    {% if upcoming_payments %}
                        {% for booking in upcoming_payments %}
                        <li class="p-4 flex justify-between items-center bg-yellow-100 text-yellow-700 rounded-lg mb-2">
                            <div>
                                <span class="font-bold">الحجز رقم: {{ booking.booking_number }}</span>
                                <span class="mr-2">- العميل: <span class="font-bold">{{ booking.customer_name }}</span></span>
                                <span class="mr-2">- المبلغ المتبقي: <span class="text-red-600 font-bold">{{ booking.selling_price|sub:booking.amount_paid }}</span></span>
                                <span class="mr-2">- تاريخ الاستحقاق: <span class="font-bold">{{ booking.last_payment_date|date:"Y-m-d" }}</span></span>
                            </div>
                            <div class="flex space-x-2 space-x-reverse">
                                <a href="{% url 'edit_booking' booking.id %}" class="bg-yellow-500 hover:bg-yellow-600 text-white text-sm py-1 px-3 rounded-md transition duration-300">
                                    <i class="bi bi-pencil-square ml-1"></i> تعديل
                                </a>
                            </div>
                        </li>
                        {% endfor %}
                    {% else %}
                    <p class="text-center text-gray-500 mt-4">لا توجد دفعات مستحقة قادمة.</p>
                    {% endif %}
                </ul>
            </div>

            <!-- Search and Filter Section -->
            <div class="bg-white rounded-xl shadow-lg p-6 mb-8">
                <div class="flex items-center justify-between border-b pb-4 mb-4">
                    <h2 class="text-xl font-semibold text-gray-800"><i class="bi bi-funnel-fill text-blue-600 ml-2"></i> بحث وتصفية</h2>
                    <a href="{% url 'add_booking' %}" class="bg-green-600 hover:bg-green-700 text-white py-2 px-4 rounded-lg transition duration-300 shadow-md">
                        <i class="bi bi-plus-circle ml-1"></i> إضافة حجز جديد
                    </a>
                </div>
                <form id="search-form" class="grid grid-cols-1 md:grid-cols-3 gap-4">
                    <div>
                        <label for="search" class="block text-sm font-medium text-gray-700 mb-1">رقم الحجز أو اسم العميل</label>
                        <input type="text" name="search" id="search" class="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500">
                    </div>
                    <div>
                        <label for="start_date" class="block text-sm font-medium text-gray-700 mb-1">تاريخ البداية</label>
                        <input type="date" name="start_date" id="start_date" class="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500">
                    </div>
                    <div>
                        <label for="end_date" class="block text-sm font-medium text-gray-700 mb-1">تاريخ النهاية</label>
                        <input type="date" name="end_date" id="end_date" class="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500">
                    </div>
                    <div class="md:col-span-3 text-left mt-2">
                        <button type="submit" class="bg-blue-600 hover:bg-blue-700 text-white py-2 px-6 rounded-lg transition duration-300 shadow-md">
                            <i class="bi bi-search ml-1"></i> بحث
                        </button>
                    </div>
                </form>
            </div>

            <!-- Bookings List Section -->
            <div class="bg-white rounded-xl shadow-lg overflow-x-auto p-6">
                <div class="flex items-center justify-between border-b pb-4 mb-4">
                    <h2 class="text-xl font-semibold text-gray-800"><i class="bi bi-list-ul text-green-600 ml-2"></i> قائمة الحجوزات</h2>
                </div>
                <table class="min-w-full text-center divide-y divide-gray-200">
                    <thead class="bg-gray-800 text-white">
                        <tr>
                            <th scope="col" class="py-3 px-6 text-sm font-semibold">رقم الحجز</th>
                            <th scope="col" class="py-3 px-6 text-sm font-semibold">اسم العميل</th>
                            <th scope="col" class="py-3 px-6 text-sm font-semibold">نوع الخدمة</th>
                            <th scope="col" class="py-3 px-6 text-sm font-semibold">تاريخ الحجز</th>
                            <th scope="col" class="py-3 px-6 text-sm font-semibold">سعر البيع</th>
                            <th scope="col" class="py-3 px-6 text-sm font-semibold">المبلغ المدفوع</th>
                            <th scope="col" class="py-3 px-6 text-sm font-semibold">الربح</th>
                            <th scope="col" class="py-3 px-6 text-sm font-semibold">الإجراءات</th>
                        </tr>
                    </thead>
                    <tbody id="bookingsTableBody" class="bg-white divide-y divide-gray-200">
                        {% if bookings %}
                            {% for booking in bookings %}
                            <tr class="hover:bg-gray-100 transition duration-300 booking-row" data-customer-name="{{ booking.customer_name }}" data-booking-number="{{ booking.booking_number }}" data-booking-date="{{ booking.booking_date|date:'Y-m-d' }}">
                                <td class="py-3 px-6 whitespace-nowrap">{{ booking.booking_number }}</td>
                                <td class="py-3 px-6 whitespace-nowrap">{{ booking.customer_name }}</td>
                                <td class="py-3 px-6 whitespace-nowrap">{{ booking.service_type }}</td>
                                <td class="py-3 px-6 whitespace-nowrap">{{ booking.booking_date }}</td>
                                <td class="py-3 px-6 whitespace-nowrap">{{ booking.selling_price }}</td>
                                <td class="py-3 px-6 whitespace-nowrap">{{ booking.amount_paid }}</td>
                                <td class="py-3 px-6 whitespace-nowrap">{{ booking.profit }}</td>
                                <td class="py-3 px-6 whitespace-nowrap">
                                    <div class="flex space-x-2 space-x-reverse justify-center">
                                        <a href="{% url 'edit_booking' booking.id %}" class="bg-yellow-500 hover:bg-yellow-600 text-white text-sm py-1 px-3 rounded-md transition duration-300">
                                            <i class="bi bi-pencil-square ml-1"></i> تعديل
                                        </a>
                                    </div>
                                </td>
                            </tr>
                            {% endfor %}
                        {% else %}
                        <tr>
                            <td colspan="8" class="py-4 text-center text-gray-500">لا توجد حجوزات مضافة حتى الآن.</td>
                        </tr>
                        {% endif %}
                        <tr id="no-results-row" class="hidden">
                            <td colspan="8" class="py-4 text-center text-gray-500">لا توجد نتائج بحث مطابقة.</td>
                        </tr>
                    </tbody>
                </table>
            </div>

            <!-- Footer for spacing on small screens -->
            <div class="h-16 md:hidden"></div>

        </main>
    </div>

    <script>
        document.addEventListener('DOMContentLoaded', function() {
            const searchForm = document.getElementById('search-form');
            const searchInput = document.getElementById('search');
            const startDateInput = document.getElementById('start_date');
            const endDateInput = document.getElementById('end_date');
            const rows = document.querySelectorAll('.booking-row');
            const noResultsRow = document.getElementById('no-results-row');

            searchForm.addEventListener('submit', function(e) {
                e.preventDefault();
                const searchText = searchInput.value.toLowerCase();
                const startDate = startDateInput.value;
                const endDate = endDateInput.value;
                let foundResults = false;

                rows.forEach(row => {
                    const customerName = row.dataset.customerName.toLowerCase();
                    const bookingNumber = row.dataset.bookingNumber.toLowerCase();
                    const bookingDate = row.dataset.bookingDate;

                    const matchesSearch = searchText === '' || customerName.includes(searchText) || bookingNumber.includes(searchText);
                    
                    let matchesDate = true;
                    if (startDate && bookingDate < startDate) {
                        matchesDate = false;
                    }
                    if (endDate && bookingDate > endDate) {
                        matchesDate = false;
                    }

                    if (matchesSearch && matchesDate) {
                        row.style.display = '';
                        foundResults = true;
                    } else {
                        row.style.display = 'none';
                    }
                });

                if (foundResults) {
                    noResultsRow.classList.add('hidden');
                } else {
                    noResultsRow.classList.remove('hidden');
                }
            });
        });
    </script>
</body>
</html>

=========
ANALYTICS_DASHBORAD.HTML<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>لوحة تحكم التحليلات</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        body {
            font-family: Arial, sans-serif;
            background-color: #f4f7f9;
            margin: 0;
            padding: 0;
            color: #333;
        }
        .sidebar {
            width: 250px;
            background-color: #fff;
            position: fixed;
            top: 0;
            right: 0;
            height: 100%;
            padding: 20px;
            box-shadow: -2px 0 5px rgba(0,0,0,0.1);
        }
        .sidebar h2 {
            text-align: center;
            color: #4a4a4a;
        }
        .sidebar ul {
            list-style-type: none;
            padding: 0;
            margin-top: 30px;
        }
        .sidebar ul li {
            margin-bottom: 10px;
        }
        .sidebar ul li a {
            display: block;
            padding: 10px 15px;
            text-decoration: none;
            color: #555;
            border-radius: 5px;
            transition: background-color 0.3s, color 0.3s;
        }
        .sidebar ul li a:hover,
        .sidebar ul li a.active {
            background-color: #007bff;
            color: #fff;
        }
        .content {
            margin-right: 270px;
            padding: 20px;
        }
        .header {
            background-color: #fff;
            padding: 20px;
            border-radius: 8px;
            box-shadow: 0 2px 5px rgba(0,0,0,0.1);
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 20px;
        }
        .header h1 {
            margin: 0;
            font-size: 24px;
        }
        .analytics-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 20px;
            margin-bottom: 20px;
        }
        .chart-card {
            background-color: #fff;
            padding: 20px;
            border-radius: 8px;
            box-shadow: 0 2px 5px rgba(0,0,0,0.1);
        }
        .btn-export {
            padding: 10px 15px;
            background-color: #28a745;
            color: #fff;
            border-radius: 5px;
            text-decoration: none;
            display: inline-block;
            margin-top: 20px;
        }
    </style>
</head>
<body>

    <div class="sidebar">
        <h2>نظام الحجوزات</h2>
        <ul>
            <li><a href="{% url 'agent_dashboard' %}"><i class="fas fa-chart-line"></i> لوحة تحكم الوكيل</a></li>
            <li><a href="{% url 'add_booking' %}"><i class="fas fa-plus"></i> إضافة حجز جديد</a></li>
            <li><a href="{% url 'analytics_dashboard' %}" class="active"><i class="fas fa-chart-pie"></i> التقارير</a></li>
            <li><a href="{% url 'agent_logout' %}"><i class="fas fa-sign-out-alt"></i> تسجيل الخروج</a></li>
        </ul>
    </div>

    <div class="content">
        <div class="header">
            <h1>التقارير والتحليلات</h1>
        </div>

        <div class="analytics-grid">
            <div class="chart-card">
                <h3>الحجوزات حسب الوكيل</h3>
                <canvas id="bookingsByAgentChart"></canvas>
            </div>
            <div class="chart-card">
                <h3>الحجوزات حسب نوع الخدمة</h3>
                <canvas id="bookingsByServiceChart"></canvas>
            </div>
        </div>

        <div style="text-align: center;">
            <a href="{% url 'export_bookings_csv' %}" class="btn-export">
                <i class="fas fa-download"></i> تصدير البيانات إلى CSV
            </a>
        </div>
    </div>

    <script>
        document.addEventListener('DOMContentLoaded', function() {
            // بيانات من Django
            const bookingsByAgentData = JSON.parse('{{ bookings_by_agent|safe }}');
            const bookingsByServiceData = JSON.parse('{{ bookings_by_service|safe }}');

            // إعداد الرسم البياني للحجوزات حسب الوكيل
            const agentLabels = bookingsByAgentData.map(item => item.agent__username);
            const agentCounts = bookingsByAgentData.map(item => item.count);
            const agentColors = agentLabels.map((_, i) => `hsl(${i * 30}, 70%, 50%)`);

            const bookingsByAgentCtx = document.getElementById('bookingsByAgentChart').getContext('2d');
            new Chart(bookingsByAgentCtx, {
                type: 'bar',
                data: {
                    labels: agentLabels,
                    datasets: [{
                        label: '# عدد الحجوزات',
                        data: agentCounts,
                        backgroundColor: agentColors,
                        borderColor: agentColors.map(c => c.replace('70%', '50%')),
                        borderWidth: 1
                    }]
                },
                options: {
                    responsive: true,
                    scales: {
                        y: {
                            beginAtZero: true
                        }
                    }
                }
            });

            // إعداد الرسم البياني للحجوزات حسب نوع الخدمة
            const serviceLabels = bookingsByServiceData.map(item => item.service_type);
            const serviceCounts = bookingsByServiceData.map(item => item.count);
            const serviceColors = serviceLabels.map((_, i) => `hsl(${i * 60}, 60%, 50%)`);

            const bookingsByServiceCtx = document.getElementById('bookingsByServiceChart').getContext('2d');
            new Chart(bookingsByServiceCtx, {
                type: 'doughnut',
                data: {
                    labels: serviceLabels,
                    datasets: [{
                        label: '# عدد الحجوزات',
                        data: serviceCounts,
                        backgroundColor: serviceColors,
                        hoverOffset: 4
                    }]
                },
                options: {
                    responsive: true,
                }
            });
        });
    </script>

</body>
</html>
==========
DELETE_BOOKING.HTML<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Delete Booking</title>
    <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-gray-100 font-sans leading-normal tracking-normal">
    <div class="container mx-auto p-4 md:p-8">
        <div class="bg-white p-6 rounded-lg shadow-md max-w-md mx-auto text-center">
            <h1 class="text-2xl font-bold text-gray-800 mb-4">Confirm Deletion</h1>
            <p class="text-gray-600 mb-6">Are you sure you want to delete the booking for <strong>{{ booking.customer_name }}</strong>?</p>
            <form method="post" class="flex justify-center space-x-4">
                {% csrf_token %}
                <button type="submit" class="px-6 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 transition duration-300">Yes, Delete</button>
                <a href="{% url 'agent_dashboard' %}" class="px-6 py-2 border border-gray-300 rounded-lg text-gray-700 hover:bg-gray-200 transition duration-300">Cancel</a>
            </form>
        </div>
    </div>
</body>
</html>
=======
EDIT_BOOKING.HTML<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>تعديل الحجز</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0-beta3/css/all.min.css" rel="stylesheet">
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Tajawal:wght@400;700&display=swap');
        body {
            font-family: 'Tajawal', sans-serif;
        }
        .container-grid {
            display: grid;
            grid-template-columns: 1fr;
            gap: 2rem;
        }
        @media (min-width: 1024px) {
            .container-grid {
                grid-template-columns: 1fr 4fr;
            }
        }
    </style>
</head>
<body class="bg-gray-100 font-sans leading-normal tracking-normal text-right">
    <div class="min-h-screen flex flex-col lg:flex-row">
        <!-- Sidebar Navigation -->
        <aside class="w-full lg:w-64 bg-white p-6 shadow-xl rounded-b-lg lg:rounded-l-lg lg:rounded-r-none mb-6 lg:mb-0 lg:mr-6">
            <h1 class="text-2xl font-bold text-gray-800 mb-6">نظام الحجوزات</h1>
            <nav class="space-y-4">
                <a href="{% url 'agent_dashboard' %}" class="flex items-center px-4 py-2 text-gray-700 hover:bg-gray-200 rounded-lg transition-colors duration-200">
                    <i class="fas fa-home ml-3"></i> لوحة التحكم
                </a>
                <a href="{% url 'add_booking' %}" class="flex items-center px-4 py-2 text-gray-700 hover:bg-gray-200 rounded-lg transition-colors duration-200">
                    <i class="fas fa-plus-circle ml-3"></i> إضافة حجز جديد
                </a>
                <a href="{% url 'analytics_dashboard' %}" class="flex items-center px-4 py-2 text-gray-700 hover:bg-gray-200 rounded-lg transition-colors duration-200">
                    <i class="fas fa-chart-pie ml-3"></i> التقارير
                </a>
                <a href="{% url 'admin:logout' %}" class="flex items-center px-4 py-2 text-red-600 hover:bg-red-100 rounded-lg transition-colors duration-200 mt-8">
                    <i class="fas fa-sign-out-alt ml-3"></i> تسجيل الخروج
                </a>
            </nav>
        </aside>

        <!-- Main Content -->
        <main class="flex-1 p-4 md:p-8 bg-gray-100">
            <h1 class="text-3xl md:text-4xl font-bold text-gray-800 mb-6">نموذج تعديل الحجز</h1>
            
            <form method="post" class="bg-white p-6 md:p-10 rounded-lg shadow-xl" id="bookingForm">
                {% csrf_token %}
                
                <!-- تفاصيل الحجز -->
                <div class="mb-8 p-6 bg-gray-50 rounded-lg border border-gray-200">
                    <h2 class="text-2xl font-semibold text-gray-700 mb-4">1. تفاصيل الحجز</h2>
                    <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
                        <div>
                            <label for="id_booking_number" class="block text-gray-700 font-medium mb-1">رقم الحجز</label>
                            <input type="text" name="booking_number" id="id_booking_number" value="{{ form.booking_number.value|default:'' }}" required class="w-full p-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-600 transition duration-200">
                        </div>
                        <div>
                            <label for="id_booking_type" class="block text-gray-700 font-medium mb-1">نوع الحجز</label>
                            <select name="booking_type" id="id_booking_type" class="w-full p-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-600 transition duration-200">
                                <option value="new" {% if form.booking_type.value == 'new' %}selected{% endif %}>جديد</option>
                                <option value="installment" {% if form.booking_type.value == 'installment' %}selected{% endif %}>تقسيط</option>
                                <option value="edit" {% if form.booking_type.value == 'edit' %}selected{% endif %}>تعديل</option>
                                <option value="cancel" {% if form.booking_type.value == 'cancel' %}selected{% endif %}>إلغاء</option>
                            </select>
                        </div>
                        <div>
                            <label for="id_booking_date" class="block text-gray-700 font-medium mb-1">تاريخ الحجز</label>
                            <input type="date" name="booking_date" id="id_booking_date" value="{{ form.booking_date.value|date:'Y-m-d' }}" required class="w-full p-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-600 transition duration-200">
                        </div>
                    </div>
                </div>

                <!-- بيانات العميل -->
                <div class="mb-8 p-6 bg-gray-50 rounded-lg border border-gray-200">
                    <h2 class="text-2xl font-semibold text-gray-700 mb-4">2. بيانات العميل</h2>
                    <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
                        <div>
                            <label for="id_customer_name" class="block text-gray-700 font-medium mb-1">الاسم</label>
                            <input type="text" name="customer_name" id="id_customer_name" value="{{ form.customer_name.value|default:'' }}" required class="w-full p-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-600 transition duration-200">
                        </div>
                        <div>
                            <label for="id_phone_number" class="block text-gray-700 font-medium mb-1">رقم التليفون</label>
                            <input type="text" name="phone_number" id="id_phone_number" value="{{ form.phone_number.value|default:'' }}" class="w-full p-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-600 transition duration-200">
                        </div>
                        <div>
                            <label for="id_email" class="block text-gray-700 font-medium mb-1">البريد الإلكتروني</label>
                            <input type="email" name="email" id="id_email" value="{{ form.email.value|default:'' }}" class="w-full p-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-600 transition duration-200">
                        </div>
                        <div>
                            <label for="id_nationality" class="block text-gray-700 font-medium mb-1">الجنسية</label>
                            <input type="text" name="nationality" id="id_nationality" value="{{ form.nationality.value|default:'' }}" required class="w-full p-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-600 transition duration-200">
                        </div>
                        <div>
                            <label for="id_booking_method" class="block text-gray-700 font-medium mb-1">طريقة الحجز</label>
                            <select name="booking_method" id="id_booking_method" class="w-full p-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-600 transition duration-200">
                                <option value="whatsapp" {% if form.booking_method.value == 'whatsapp' %}selected{% endif %}>واتساب</option>
                                <option value="call" {% if form.booking_method.value == 'call' %}selected{% endif %}>مكالمة</option>
                                <option value="old_client" {% if form.booking_method.value == 'old_client' %}selected{% endif %}>عميل قديم</option>
                            </select>
                        </div>
                    </div>
                </div>

                <!-- تفاصيل الحجز -->
                <div class="mb-8 p-6 bg-gray-50 rounded-lg border border-gray-200">
                    <h2 class="text-2xl font-semibold text-gray-700 mb-4">3. تفاصيل الخدمة</h2>
                    <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
                        <div>
                            <label for="id_service_type" class="block text-gray-700 font-medium mb-1">نوع الخدمة</label>
                            <select name="service_type" id="id_service_type" class="w-full p-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-600 transition duration-200">
                                <option value="flight" {% if form.service_type.value == 'flight' %}selected{% endif %}>طيران</option>
                                <option value="hotel" {% if form.service_type.value == 'hotel' %}selected{% endif %}>فندق</option>
                                <option value="delivery" {% if form.service_type.value == 'delivery' %}selected{% endif %}>توصيل</option>
                                <option value="visa" {% if form.service_type.value == 'visa' %}selected{% endif %}>فيزا</option>
                            </select>
                        </div>
                        <div>
                            <label for="id_service_provider" class="block text-gray-700 font-medium mb-1">الوكيل</label>
                            <select name="service_provider" id="id_service_provider" class="w-full p-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-600 transition duration-200">
                                <option value="smile" {% if form.service_provider.value == 'smile' %}selected{% endif %}>سمايل</option>
                                <option value="amadeus" {% if form.service_provider.value == 'amadeus' %}selected{% endif %}>أماديوس</option>
                                <option value="other" {% if form.service_provider.value == 'other' %}selected{% endif %}>غيره</option>
                            </select>
                        </div>
                        <div>
                            <label for="id_check_in_date" class="block text-gray-700 font-medium mb-1">تاريخ الدخول</label>
                            <input type="date" name="check_in_date" id="id_check_in_date" value="{{ form.check_in_date.value|date:'Y-m-d' }}" required class="w-full p-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-600 transition duration-200">
                        </div>
                    </div>
                </div>

                <!-- تفاصيل الدفع -->
                <div class="mb-8 p-6 bg-gray-50 rounded-lg border border-gray-200">
                    <h2 class="text-2xl font-semibold text-gray-700 mb-4">4. تفاصيل الدفع</h2>
                    <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
                        <div>
                            <label for="id_net_price" class="block text-gray-700 font-medium mb-1">السعر نت</label>
                            <input type="number" step="0.01" name="net_price" id="id_net_price" value="{{ form.net_price.value|default:'' }}" required class="w-full p-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-600 transition duration-200">
                        </div>
                        <div>
                            <label for="id_selling_price" class="block text-gray-700 font-medium mb-1">سعر البيع</label>
                            <input type="number" step="0.01" name="selling_price" id="id_selling_price" value="{{ form.selling_price.value|default:'' }}" required class="w-full p-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-600 transition duration-200">
                        </div>
                        <div>
                            <label for="id_amount_paid" class="block text-gray-700 font-medium mb-1">المبلغ المدفوع</label>
                            <input type="number" step="0.01" name="amount_paid" id="id_amount_paid" value="{{ form.amount_paid.value|default:'' }}" required class="w-full p-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-600 transition duration-200">
                            <div id="payment-status" class="mt-2 text-sm"></div>
                        </div>
                        <div>
                            <label for="profit-amount" class="block text-gray-700 font-medium mb-1">الربح</label>
                            <input type="text" id="profit-amount" readonly class="w-full p-3 bg-gray-200 border border-gray-300 rounded-lg">
                        </div>
                        <div>
                            <label for="id_currency" class="block text-gray-700 font-medium mb-1">الدفع (العملة)</label>
                            <select name="currency" id="id_currency" class="w-full p-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-600 transition duration-200">
                                <option value="kwd" {% if form.currency.value == 'kwd' %}selected{% endif %}>KWD</option>
                                <option value="sar" {% if form.currency.value == 'sar' %}selected{% endif %}>SAR</option>
                                <option value="aed" {% if form.currency.value == 'aed' %}selected{% endif %}>AED</option>
                            </select>
                        </div>
                        <div>
                            <label for="id_payment_method" class="block text-gray-700 font-medium mb-1">طريقة السداد</label>
                            <select name="payment_method" id="id_payment_method" required class="w-full p-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-600 transition duration-200">
                                <option value="link" {% if form.payment_method.value == 'link' %}selected{% endif %}>رابط سداد</option>
                                <option value="bank_transfer" {% if form.payment_method.value == 'bank_transfer' %}selected{% endif %}>تحويل بنكي</option>
                                <option value="cash" {% if form.payment_method.value == 'cash' %}selected{% endif %}>كاش</option>
                            </select>
                        </div>
                        <div id="remaining-amount-container" class="hidden">
                            <label for="remaining-amount" class="block text-gray-700 font-medium mb-1">المبلغ المتبقي</label>
                            <input type="text" id="remaining-amount" readonly class="w-full p-3 bg-gray-200 border border-gray-300 rounded-lg">
                        </div>
                        <div id="last-payment-date-container" class="hidden">
                            <label for="id_last_payment_date" class="block text-gray-700 font-medium mb-1">آخر يوم للسداد</label>
                            <input type="date" name="last_payment_date" id="id_last_payment_date" value="{{ form.last_payment_date.value|date:'Y-m-d' }}" class="w-full p-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-600 transition duration-200">
                        </div>
                        <div id="file-upload-container" class="hidden">
                            <label for="file-upload" class="block text-gray-700 font-medium mb-1">إرفاق ملف</label>
                            <input type="file" id="file-upload" class="w-full p-3 border border-gray-300 rounded-lg">
                        </div>
                        <div id="link-upload-container" class="hidden">
                            <label for="link-upload" class="block text-gray-700 font-medium mb-1">رابط السداد</label>
                            <input type="url" id="link-upload" class="w-full p-3 border border-gray-300 rounded-lg">
                        </div>
                    </div>
                </div>

                <!-- إرفاق المستندات والملاحظات -->
                <div class="mb-8 p-6 bg-gray-50 rounded-lg border border-gray-200">
                    <h2 class="text-2xl font-semibold text-gray-700 mb-4">5. المستندات والملاحظات</h2>
                    <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
                        <div>
                            <label for="voucher_file" class="block text-gray-700 font-medium mb-1">إرفاق الفاوتشر</label>
                            <input type="file" name="voucher_file" id="voucher_file" class="w-full p-3 border border-gray-300 rounded-lg">
                        </div>
                        <div>
                            <label for="invoice_file" class="block text-gray-700 font-medium mb-1">إرفاق الفاتورة</label>
                            <input type="file" name="invoice_file" id="invoice_file" class="w-full p-3 border border-gray-300 rounded-lg">
                        </div>
                        <div class="md:col-span-2">
                            <label for="id_notes" class="block text-gray-700 font-medium mb-1">ملاحظات</label>
                            <textarea name="notes" id="id_notes" rows="4" class="w-full p-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-600 transition duration-200">{{ form.notes.value|default:'' }}</textarea>
                        </div>
                    </div>
                </div>

                <!-- أزرار الإرسال -->
                <div class="flex flex-col md:flex-row gap-4 justify-center">
                    <button type="submit" name="action" value="save_and_return" class="px-6 py-3 bg-indigo-600 text-white rounded-lg shadow-md hover:bg-indigo-700 transition duration-300">
                        حفظ والعودة للصفحة الرئيسية
                    </button>
                    <button type="submit" name="action" value="save_and_new" class="px-6 py-3 bg-gray-800 text-white rounded-lg shadow-md hover:bg-gray-900 transition duration-300">
                        حفظ وعمل حجز جديد
                    </button>
                </div>
            </form>
        </main>
    </div>
    
    <script>
        const amountPaidInput = document.getElementById('id_amount_paid');
        const sellingPriceInput = document.getElementById('id_selling_price');
        const netPriceInput = document.getElementById('id_net_price');
        const paymentStatusDiv = document.getElementById('payment-status');
        const bookingTypeSelect = document.getElementById('id_booking_type');
        const lastPaymentDateContainer = document.getElementById('last-payment-date-container');
        const remainingAmountContainer = document.getElementById('remaining-amount-container');
        const paymentMethodSelect = document.getElementById('id_payment_method');
        const fileUploadContainer = document.getElementById('file-upload-container');
        const linkUploadContainer = document.getElementById('link-upload-container');
        const remainingAmountInput = document.getElementById('remaining-amount');
        const profitInput = document.getElementById('profit-amount');


        function updatePaymentStatus() {
            const amountPaid = parseFloat(amountPaidInput.value) || 0;
            const sellingPrice = parseFloat(sellingPriceInput.value) || 0;
            const netPrice = parseFloat(netPriceInput.value) || 0;

            // Calculate profit
            const profit = (sellingPrice - netPrice).toFixed(2);
            profitInput.value = profit;
            
            paymentStatusDiv.textContent = '';
            paymentStatusDiv.classList.remove('text-red-500', 'text-green-500', 'text-yellow-500');
            
            if (sellingPrice > 0 && amountPaid > sellingPrice) {
                paymentStatusDiv.textContent = 'تحذير: المبلغ المدفوع أكبر من سعر البيع!';
                paymentStatusDiv.classList.add('text-red-500');
            } else if (sellingPrice > 0 && amountPaid < sellingPrice) {
                const remaining = (sellingPrice - amountPaid).toFixed(2);
                paymentStatusDiv.textContent = 'المبلغ المتبقي هو ' + remaining;
                paymentStatusDiv.classList.add('text-yellow-500');
                remainingAmountInput.value = remaining;
                
            } else if (sellingPrice > 0 && amountPaid === sellingPrice) {
                paymentStatusDiv.textContent = 'تم دفع المبلغ بالكامل.';
                paymentStatusDiv.classList.add('text-green-500');
            }
        }

        function toggleInstallmentFields() {
            const amountPaid = parseFloat(amountPaidInput.value) || 0;
            const sellingPrice = parseFloat(sellingPriceInput.value) || 0;
            const isInstallmentNeeded = (sellingPrice > 0 && amountPaid < sellingPrice);

            remainingAmountContainer.classList.toggle('hidden', !isInstallmentNeeded);
            lastPaymentDateContainer.classList.toggle('hidden', !isInstallmentNeeded);
        }

        function updatePaymentMethodFields() {
            const paymentMethod = paymentMethodSelect.value;
            if (paymentMethod === 'link') {
                linkUploadContainer.classList.remove('hidden');
                fileUploadContainer.classList.add('hidden');
            } else {
                fileUploadContainer.classList.remove('hidden');
                linkUploadContainer.classList.add('hidden');
            }
        }

        // Add event listeners
        amountPaidInput.addEventListener('input', () => {
            updatePaymentStatus();
            toggleInstallmentFields();
        });
        sellingPriceInput.addEventListener('input', () => {
            updatePaymentStatus();
            toggleInstallmentFields();
        });
        netPriceInput.addEventListener('input', updatePaymentStatus);
        paymentMethodSelect.addEventListener('change', updatePaymentMethodFields);

        // Initial check on page load
        document.addEventListener('DOMContentLoaded', () => {
            updatePaymentStatus();
            toggleInstallmentFields();
            updatePaymentMethodFields();
        });

        // Handle form submission logic for two buttons
        document.getElementById('bookingForm').addEventListener('submit', function(event) {
            const form = event.target;
            const action = event.submitter.value;

            // Prevent default form submission
            event.preventDefault();

            // Set a hidden input to indicate which button was clicked
            const hiddenInput = document.createElement('input');
            hiddenInput.type = 'hidden';
            hiddenInput.name = 'action_type';
            hiddenInput.value = action;
            form.appendChild(hiddenInput);

            // Re-submit the form
            form.submit();
        });
    </script>
</body>
</html>
======
LOGIN.HTML<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>تعديل الحجز</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0-beta3/css/all.min.css" rel="stylesheet">
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Tajawal:wght@400;700&display=swap');
        body {
            font-family: 'Tajawal', sans-serif;
        }
        .container-grid {
            display: grid;
            grid-template-columns: 1fr;
            gap: 2rem;
        }
        @media (min-width: 1024px) {
            .container-grid {
                grid-template-columns: 1fr 4fr;
            }
        }
    </style>
</head>
<body class="bg-gray-100 font-sans leading-normal tracking-normal text-right">
    <div class="min-h-screen flex flex-col lg:flex-row">
        <!-- Sidebar Navigation -->
        <aside class="w-full lg:w-64 bg-white p-6 shadow-xl rounded-b-lg lg:rounded-l-lg lg:rounded-r-none mb-6 lg:mb-0 lg:mr-6">
            <h1 class="text-2xl font-bold text-gray-800 mb-6">نظام الحجوزات</h1>
            <nav class="space-y-4">
                <a href="{% url 'agent_dashboard' %}" class="flex items-center px-4 py-2 text-gray-700 hover:bg-gray-200 rounded-lg transition-colors duration-200">
                    <i class="fas fa-home ml-3"></i> لوحة التحكم
                </a>
                <a href="{% url 'add_booking' %}" class="flex items-center px-4 py-2 text-gray-700 hover:bg-gray-200 rounded-lg transition-colors duration-200">
                    <i class="fas fa-plus-circle ml-3"></i> إضافة حجز جديد
                </a>
                <a href="{% url 'analytics_dashboard' %}" class="flex items-center px-4 py-2 text-gray-700 hover:bg-gray-200 rounded-lg transition-colors duration-200">
                    <i class="fas fa-chart-pie ml-3"></i> التقارير
                </a>
                <a href="{% url 'admin:logout' %}" class="flex items-center px-4 py-2 text-red-600 hover:bg-red-100 rounded-lg transition-colors duration-200 mt-8">
                    <i class="fas fa-sign-out-alt ml-3"></i> تسجيل الخروج
                </a>
            </nav>
        </aside>

        <!-- Main Content -->
        <main class="flex-1 p-4 md:p-8 bg-gray-100">
            <h1 class="text-3xl md:text-4xl font-bold text-gray-800 mb-6">نموذج تعديل الحجز</h1>
            
            <form method="post" class="bg-white p-6 md:p-10 rounded-lg shadow-xl" id="bookingForm">
                {% csrf_token %}
                
                <!-- تفاصيل الحجز -->
                <div class="mb-8 p-6 bg-gray-50 rounded-lg border border-gray-200">
                    <h2 class="text-2xl font-semibold text-gray-700 mb-4">1. تفاصيل الحجز</h2>
                    <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
                        <div>
                            <label for="id_booking_number" class="block text-gray-700 font-medium mb-1">رقم الحجز</label>
                            <input type="text" name="booking_number" id="id_booking_number" value="{{ form.booking_number.value|default:'' }}" required class="w-full p-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-600 transition duration-200">
                        </div>
                        <div>
                            <label for="id_booking_type" class="block text-gray-700 font-medium mb-1">نوع الحجز</label>
                            <select name="booking_type" id="id_booking_type" class="w-full p-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-600 transition duration-200">
                                <option value="new" {% if form.booking_type.value == 'new' %}selected{% endif %}>جديد</option>
                                <option value="installment" {% if form.booking_type.value == 'installment' %}selected{% endif %}>تقسيط</option>
                                <option value="edit" {% if form.booking_type.value == 'edit' %}selected{% endif %}>تعديل</option>
                                <option value="cancel" {% if form.booking_type.value == 'cancel' %}selected{% endif %}>إلغاء</option>
                            </select>
                        </div>
                        <div>
                            <label for="id_booking_date" class="block text-gray-700 font-medium mb-1">تاريخ الحجز</label>
                            <input type="date" name="booking_date" id="id_booking_date" value="{{ form.booking_date.value|date:'Y-m-d' }}" required class="w-full p-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-600 transition duration-200">
                        </div>
                    </div>
                </div>

                <!-- بيانات العميل -->
                <div class="mb-8 p-6 bg-gray-50 rounded-lg border border-gray-200">
                    <h2 class="text-2xl font-semibold text-gray-700 mb-4">2. بيانات العميل</h2>
                    <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
                        <div>
                            <label for="id_customer_name" class="block text-gray-700 font-medium mb-1">الاسم</label>
                            <input type="text" name="customer_name" id="id_customer_name" value="{{ form.customer_name.value|default:'' }}" required class="w-full p-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-600 transition duration-200">
                        </div>
                        <div>
                            <label for="id_phone_number" class="block text-gray-700 font-medium mb-1">رقم التليفون</label>
                            <input type="text" name="phone_number" id="id_phone_number" value="{{ form.phone_number.value|default:'' }}" class="w-full p-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-600 transition duration-200">
                        </div>
                        <div>
                            <label for="id_email" class="block text-gray-700 font-medium mb-1">البريد الإلكتروني</label>
                            <input type="email" name="email" id="id_email" value="{{ form.email.value|default:'' }}" class="w-full p-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-600 transition duration-200">
                        </div>
                        <div>
                            <label for="id_nationality" class="block text-gray-700 font-medium mb-1">الجنسية</label>
                            <input type="text" name="nationality" id="id_nationality" value="{{ form.nationality.value|default:'' }}" required class="w-full p-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-600 transition duration-200">
                        </div>
                        <div>
                            <label for="id_booking_method" class="block text-gray-700 font-medium mb-1">طريقة الحجز</label>
                            <select name="booking_method" id="id_booking_method" class="w-full p-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-600 transition duration-200">
                                <option value="whatsapp" {% if form.booking_method.value == 'whatsapp' %}selected{% endif %}>واتساب</option>
                                <option value="call" {% if form.booking_method.value == 'call' %}selected{% endif %}>مكالمة</option>
                                <option value="old_client" {% if form.booking_method.value == 'old_client' %}selected{% endif %}>عميل قديم</option>
                            </select>
                        </div>
                    </div>
                </div>

                <!-- تفاصيل الحجز -->
                <div class="mb-8 p-6 bg-gray-50 rounded-lg border border-gray-200">
                    <h2 class="text-2xl font-semibold text-gray-700 mb-4">3. تفاصيل الخدمة</h2>
                    <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
                        <div>
                            <label for="id_service_type" class="block text-gray-700 font-medium mb-1">نوع الخدمة</label>
                            <select name="service_type" id="id_service_type" class="w-full p-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-600 transition duration-200">
                                <option value="flight" {% if form.service_type.value == 'flight' %}selected{% endif %}>طيران</option>
                                <option value="hotel" {% if form.service_type.value == 'hotel' %}selected{% endif %}>فندق</option>
                                <option value="delivery" {% if form.service_type.value == 'delivery' %}selected{% endif %}>توصيل</option>
                                <option value="visa" {% if form.service_type.value == 'visa' %}selected{% endif %}>فيزا</option>
                            </select>
                        </div>
                        <div>
                            <label for="id_service_provider" class="block text-gray-700 font-medium mb-1">الوكيل</label>
                            <select name="service_provider" id="id_service_provider" class="w-full p-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-600 transition duration-200">
                                <option value="smile" {% if form.service_provider.value == 'smile' %}selected{% endif %}>سمايل</option>
                                <option value="amadeus" {% if form.service_provider.value == 'amadeus' %}selected{% endif %}>أماديوس</option>
                                <option value="other" {% if form.service_provider.value == 'other' %}selected{% endif %}>غيره</option>
                            </select>
                        </div>
                        <div>
                            <label for="id_check_in_date" class="block text-gray-700 font-medium mb-1">تاريخ الدخول</label>
                            <input type="date" name="check_in_date" id="id_check_in_date" value="{{ form.check_in_date.value|date:'Y-m-d' }}" required class="w-full p-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-600 transition duration-200">
                        </div>
                    </div>
                </div>

                <!-- تفاصيل الدفع -->
                <div class="mb-8 p-6 bg-gray-50 rounded-lg border border-gray-200">
                    <h2 class="text-2xl font-semibold text-gray-700 mb-4">4. تفاصيل الدفع</h2>
                    <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
                        <div>
                            <label for="id_net_price" class="block text-gray-700 font-medium mb-1">السعر نت</label>
                            <input type="number" step="0.01" name="net_price" id="id_net_price" value="{{ form.net_price.value|default:'' }}" required class="w-full p-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-600 transition duration-200">
                        </div>
                        <div>
                            <label for="id_selling_price" class="block text-gray-700 font-medium mb-1">سعر البيع</label>
                            <input type="number" step="0.01" name="selling_price" id="id_selling_price" value="{{ form.selling_price.value|default:'' }}" required class="w-full p-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-600 transition duration-200">
                        </div>
                        <div>
                            <label for="id_amount_paid" class="block text-gray-700 font-medium mb-1">المبلغ المدفوع</label>
                            <input type="number" step="0.01" name="amount_paid" id="id_amount_paid" value="{{ form.amount_paid.value|default:'' }}" required class="w-full p-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-600 transition duration-200">
                            <div id="payment-status" class="mt-2 text-sm"></div>
                        </div>
                        <div>
                            <label for="profit-amount" class="block text-gray-700 font-medium mb-1">الربح</label>
                            <input type="text" id="profit-amount" readonly class="w-full p-3 bg-gray-200 border border-gray-300 rounded-lg">
                        </div>
                        <div>
                            <label for="id_currency" class="block text-gray-700 font-medium mb-1">الدفع (العملة)</label>
                            <select name="currency" id="id_currency" class="w-full p-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-600 transition duration-200">
                                <option value="kwd" {% if form.currency.value == 'kwd' %}selected{% endif %}>KWD</option>
                                <option value="sar" {% if form.currency.value == 'sar' %}selected{% endif %}>SAR</option>
                                <option value="aed" {% if form.currency.value == 'aed' %}selected{% endif %}>AED</option>
                            </select>
                        </div>
                        <div>
                            <label for="id_payment_method" class="block text-gray-700 font-medium mb-1">طريقة السداد</label>
                            <select name="payment_method" id="id_payment_method" required class="w-full p-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-600 transition duration-200">
                                <option value="link" {% if form.payment_method.value == 'link' %}selected{% endif %}>رابط سداد</option>
                                <option value="bank_transfer" {% if form.payment_method.value == 'bank_transfer' %}selected{% endif %}>تحويل بنكي</option>
                                <option value="cash" {% if form.payment_method.value == 'cash' %}selected{% endif %}>كاش</option>
                            </select>
                        </div>
                        <div id="remaining-amount-container" class="hidden">
                            <label for="remaining-amount" class="block text-gray-700 font-medium mb-1">المبلغ المتبقي</label>
                            <input type="text" id="remaining-amount" readonly class="w-full p-3 bg-gray-200 border border-gray-300 rounded-lg">
                        </div>
                        <div id="last-payment-date-container" class="hidden">
                            <label for="id_last_payment_date" class="block text-gray-700 font-medium mb-1">آخر يوم للسداد</label>
                            <input type="date" name="last_payment_date" id="id_last_payment_date" value="{{ form.last_payment_date.value|date:'Y-m-d' }}" class="w-full p-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-600 transition duration-200">
                        </div>
                        <div id="file-upload-container" class="hidden">
                            <label for="file-upload" class="block text-gray-700 font-medium mb-1">إرفاق ملف</label>
                            <input type="file" id="file-upload" class="w-full p-3 border border-gray-300 rounded-lg">
                        </div>
                        <div id="link-upload-container" class="hidden">
                            <label for="link-upload" class="block text-gray-700 font-medium mb-1">رابط السداد</label>
                            <input type="url" id="link-upload" class="w-full p-3 border border-gray-300 rounded-lg">
                        </div>
                    </div>
                </div>

                <!-- إرفاق المستندات والملاحظات -->
                <div class="mb-8 p-6 bg-gray-50 rounded-lg border border-gray-200">
                    <h2 class="text-2xl font-semibold text-gray-700 mb-4">5. المستندات والملاحظات</h2>
                    <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
                        <div>
                            <label for="voucher_file" class="block text-gray-700 font-medium mb-1">إرفاق الفاوتشر</label>
                            <input type="file" name="voucher_file" id="voucher_file" class="w-full p-3 border border-gray-300 rounded-lg">
                        </div>
                        <div>
                            <label for="invoice_file" class="block text-gray-700 font-medium mb-1">إرفاق الفاتورة</label>
                            <input type="file" name="invoice_file" id="invoice_file" class="w-full p-3 border border-gray-300 rounded-lg">
                        </div>
                        <div class="md:col-span-2">
                            <label for="id_notes" class="block text-gray-700 font-medium mb-1">ملاحظات</label>
                            <textarea name="notes" id="id_notes" rows="4" class="w-full p-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-600 transition duration-200">{{ form.notes.value|default:'' }}</textarea>
                        </div>
                    </div>
                </div>

                <!-- أزرار الإرسال -->
                <div class="flex flex-col md:flex-row gap-4 justify-center">
                    <button type="submit" name="action" value="save_and_return" class="px-6 py-3 bg-indigo-600 text-white rounded-lg shadow-md hover:bg-indigo-700 transition duration-300">
                        حفظ والعودة للصفحة الرئيسية
                    </button>
                    <button type="submit" name="action" value="save_and_new" class="px-6 py-3 bg-gray-800 text-white rounded-lg shadow-md hover:bg-gray-900 transition duration-300">
                        حفظ وعمل حجز جديد
                    </button>
                </div>
            </form>
        </main>
    </div>
    
    <script>
        const amountPaidInput = document.getElementById('id_amount_paid');
        const sellingPriceInput = document.getElementById('id_selling_price');
        const netPriceInput = document.getElementById('id_net_price');
        const paymentStatusDiv = document.getElementById('payment-status');
        const bookingTypeSelect = document.getElementById('id_booking_type');
        const lastPaymentDateContainer = document.getElementById('last-payment-date-container');
        const remainingAmountContainer = document.getElementById('remaining-amount-container');
        const paymentMethodSelect = document.getElementById('id_payment_method');
        const fileUploadContainer = document.getElementById('file-upload-container');
        const linkUploadContainer = document.getElementById('link-upload-container');
        const remainingAmountInput = document.getElementById('remaining-amount');
        const profitInput = document.getElementById('profit-amount');


        function updatePaymentStatus() {
            const amountPaid = parseFloat(amountPaidInput.value) || 0;
            const sellingPrice = parseFloat(sellingPriceInput.value) || 0;
            const netPrice = parseFloat(netPriceInput.value) || 0;

            // Calculate profit
            const profit = (sellingPrice - netPrice).toFixed(2);
            profitInput.value = profit;
            
            paymentStatusDiv.textContent = '';
            paymentStatusDiv.classList.remove('text-red-500', 'text-green-500', 'text-yellow-500');
            
            if (sellingPrice > 0 && amountPaid > sellingPrice) {
                paymentStatusDiv.textContent = 'تحذير: المبلغ المدفوع أكبر من سعر البيع!';
                paymentStatusDiv.classList.add('text-red-500');
            } else if (sellingPrice > 0 && amountPaid < sellingPrice) {
                const remaining = (sellingPrice - amountPaid).toFixed(2);
                paymentStatusDiv.textContent = 'المبلغ المتبقي هو ' + remaining;
                paymentStatusDiv.classList.add('text-yellow-500');
                remainingAmountInput.value = remaining;
                
            } else if (sellingPrice > 0 && amountPaid === sellingPrice) {
                paymentStatusDiv.textContent = 'تم دفع المبلغ بالكامل.';
                paymentStatusDiv.classList.add('text-green-500');
            }
        }

        function toggleInstallmentFields() {
            const amountPaid = parseFloat(amountPaidInput.value) || 0;
            const sellingPrice = parseFloat(sellingPriceInput.value) || 0;
            const isInstallmentNeeded = (sellingPrice > 0 && amountPaid < sellingPrice);

            remainingAmountContainer.classList.toggle('hidden', !isInstallmentNeeded);
            lastPaymentDateContainer.classList.toggle('hidden', !isInstallmentNeeded);
        }

        function updatePaymentMethodFields() {
            const paymentMethod = paymentMethodSelect.value;
            if (paymentMethod === 'link') {
                linkUploadContainer.classList.remove('hidden');
                fileUploadContainer.classList.add('hidden');
            } else {
                fileUploadContainer.classList.remove('hidden');
                linkUploadContainer.classList.add('hidden');
            }
        }

        // Add event listeners
        amountPaidInput.addEventListener('input', () => {
            updatePaymentStatus();
            toggleInstallmentFields();
        });
        sellingPriceInput.addEventListener('input', () => {
            updatePaymentStatus();
            toggleInstallmentFields();
        });
        netPriceInput.addEventListener('input', updatePaymentStatus);
        paymentMethodSelect.addEventListener('change', updatePaymentMethodFields);

        // Initial check on page load
        document.addEventListener('DOMContentLoaded', () => {
            updatePaymentStatus();
            toggleInstallmentFields();
            updatePaymentMethodFields();
        });

        // Handle form submission logic for two buttons
        document.getElementById('bookingForm').addEventListener('submit', function(event) {
            const form = event.target;
            const action = event.submitter.value;

            // Prevent default form submission
            event.preventDefault();

            // Set a hidden input to indicate which button was clicked
            const hiddenInput = document.createElement('input');
            hiddenInput.type = 'hidden';
            hiddenInput.name = 'action_type';
            hiddenInput.value = action;
            form.appendChild(hiddenInput);

            // Re-submit the form
            form.submit();
        });
    </script>
</body>
</html>
======
SUPER_DASHBOARD.HTML<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Super Dashboard</title>
    <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-gray-100 font-sans leading-normal tracking-normal">
    <div class="container mx-auto p-4 md:p-8">
        <h1 class="text-3xl md:text-4xl font-bold text-gray-800 mb-4">Super Dashboard</h1>

        <!-- Dynamic Navigation Menu for Superuser -->
        <div class="bg-white p-4 rounded-lg shadow-md mb-6 flex flex-wrap gap-4 justify-center">
            <a href="{% url 'add_booking' %}" class="px-4 py-2 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 transition duration-300">Add New Booking</a>
            <a href="{% url 'agent_dashboard' %}" class="px-4 py-2 bg-gray-200 text-gray-800 rounded-lg hover:bg-gray-300 transition duration-300">My Dashboard</a>
            <a href="{% url 'team_leader_dashboard' %}" class="px-4 py-2 bg-gray-200 text-gray-800 rounded-lg hover:bg-gray-300 transition duration-300">Team Leader Dashboard</a>
            <a href="{% url 'super_dashboard' %}" class="px-4 py-2 bg-gray-200 text-gray-800 rounded-lg hover:bg-gray-300 transition duration-300">Super Dashboard</a>
            <a href="{% url 'analytics_dashboard' %}" class="px-4 py-2 bg-gray-200 text-gray-800 rounded-lg hover:bg-gray-300 transition duration-300">Analytics Dashboard</a>
        </div>
        
        <h2 class="text-2xl font-semibold text-gray-700 mb-4">All Bookings (Super View)</h2>
        {% if bookings %}
            <div class="bg-white p-6 rounded-lg shadow-md">
                <ul>
                {% for booking in bookings %}
                    <li class="border-b last:border-b-0 py-4">
                        <div class="flex flex-col md:flex-row md:justify-between md:items-center">
                            <div class="mb-2 md:mb-0">
                                <p class="text-gray-600"><strong>Agent:</strong> <span class="text-indigo-600">{{ booking.agent.username }}</span></p>
                                <p class="text-gray-600"><strong>Client:</strong> <span class="font-medium text-gray-900">{{ booking.customer_name }}</span></p>
                                <p class="text-gray-600"><strong>Service:</strong> <span class="text-sm font-medium text-gray-500">{{ booking.service_type }}</span></p>
                                <p class="text-gray-600"><strong>Date:</strong> {{ booking.booking_date }}</p>
                                <p class="text-gray-600 text-xs"><strong>Created At:</strong> {{ booking.created_at|date:"F j, Y, P" }}</p>
                            </div>
                            <div class="flex space-x-2 mt-2 md:mt-0">
                                <a href="{% url 'edit_booking_tl_super' booking.id %}" class="px-3 py-1 bg-blue-500 text-white text-sm rounded-md hover:bg-blue-600 transition duration-300">Edit</a>
                                <a href="{% url 'delete_booking_tl_super' booking.id %}" class="px-3 py-1 bg-red-500 text-white text-sm rounded-md hover:bg-red-600 transition duration-300">Delete</a>
                            </div>
                        </div>
                    </li>
                {% endfor %}
                </ul>
            </div>
        {% else %}
            <p class="text-gray-500 text-center">No bookings have been added yet.</p>
        {% endif %}

        <div class="text-center mt-8">
            <a href="{% url 'admin:logout' %}" class="inline-block px-6 py-2 border border-gray-300 rounded-lg text-gray-700 hover:bg-gray-200 transition duration-300">Logout</a>
        </div>
    </div>
</body>
</html>
=====
TEAM_LEADER_DASHBOARD.HTM
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Team Leader Dashboard</title>
    <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-gray-100 font-sans leading-normal tracking-normal">
    <div class="container mx-auto p-4 md:p-8">
        <h1 class="text-3xl md:text-4xl font-bold text-gray-800 mb-4">Team Leader Dashboard</h1>

        <!-- Dynamic Navigation Menu for Team Leader -->
        <div class="bg-white p-4 rounded-lg shadow-md mb-6 flex flex-wrap gap-4 justify-center">
            <a href="{% url 'add_booking' %}" class="px-4 py-2 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 transition duration-300">Add New Booking</a>
            <a href="{% url 'agent_dashboard' %}" class="px-4 py-2 bg-gray-200 text-gray-800 rounded-lg hover:bg-gray-300 transition duration-300">My Dashboard</a>
            <a href="{% url 'team_leader_dashboard' %}" class="px-4 py-2 bg-gray-200 text-gray-800 rounded-lg hover:bg-gray-300 transition duration-300">Team Leader Dashboard</a>
            <a href="{% url 'analytics_dashboard' %}" class="px-4 py-2 bg-gray-200 text-gray-800 rounded-lg hover:bg-gray-300 transition duration-300">Analytics Dashboard</a>
        </div>
        
        <h2 class="text-2xl font-semibold text-gray-700 mb-4">All Bookings</h2>
        {% if bookings %}
            <div class="bg-white p-6 rounded-lg shadow-md">
                <ul>
                {% for booking in bookings %}
                    <li class="border-b last:border-b-0 py-4">
                        <div class="flex flex-col md:flex-row md:justify-between md:items-center">
                            <div class="mb-2 md:mb-0">
                                <p class="text-gray-600"><strong>Agent:</strong> <span class="text-indigo-600">{{ booking.agent.username }}</span></p>
                                <p class="text-gray-600"><strong>Client:</strong> <span class="font-medium text-gray-900">{{ booking.customer_name }}</span></p>
                                <p class="text-gray-600"><strong>Service:</strong> <span class="text-sm font-medium text-gray-500">{{ booking.service_type }}</span></p>
                                <p class="text-gray-600"><strong>Date:</strong> {{ booking.booking_date }}</p>
                                <p class="text-gray-600 text-xs"><strong>Created At:</strong> {{ booking.created_at|date:"F j, Y, P" }}</p>
                            </div>
                            <div class="flex space-x-2 mt-2 md:mt-0">
                                <a href="{% url 'edit_booking_tl_super' booking.id %}" class="px-3 py-1 bg-blue-500 text-white text-sm rounded-md hover:bg-blue-600 transition duration-300">Edit</a>
                                <a href="{% url 'delete_booking_tl_super' booking.id %}" class="px-3 py-1 bg-red-500 text-white text-sm rounded-md hover:bg-red-600 transition duration-300">Delete</a>
                            </div>
                        </div>
                    </li>
                {% endfor %}
                </ul>
            </div>
        {% else %}
            <p class="text-gray-500 text-center">No bookings have been added yet.</p>
        {% endif %}

        <div class="text-center mt-8">
            <a href="{% url 'admin:logout' %}" class="inline-block px-6 py-2 border border-gray-300 rounded-lg text-gray-700 hover:bg-gray-200 transition duration-300">Logout</a>
        </div>
    </div>
</body>
</html>
