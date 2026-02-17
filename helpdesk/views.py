from __future__ import annotations

import csv
import re

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q, Count, Avg, F, DurationField, ExpressionWrapper
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .models import (
    Department,
    Ticket,
    TicketMessage,
    TicketAttachment,
    TicketCategory,
)
from .forms import TicketForm, TicketReplyForm
from .permissions import can_view_ticket, can_reply_ticket, is_dept_member

# Mentions: @username
MENTION_RE = re.compile(r"@(\w[\w\.+-]{1,30})")


# ===================== INBOXES =====================

@login_required
def my_inbox(request):
    q = request.GET.get("q", "").strip()

    qs = Ticket.objects.filter(
        Q(assigned_to=request.user) | Q(requester=request.user)
    )

    if q:
        qs = qs.filter(
            Q(subject__icontains=q)
            | Q(related_ref__icontains=q)
            | Q(tags__name__icontains=q)
        ).distinct()

    ctx = {
        "tickets": qs.select_related(
            "department", "assigned_to", "requester"
        ).prefetch_related("tags")[:300],
        "q": q,
    }
    return render(request, "helpdesk/my_inbox.html", ctx)


@login_required
def department_inbox(request, slug: str):
    dept = get_object_or_404(Department, slug=slug, is_active=True)

    if not is_dept_member(request.user, dept):
        messages.error(request, "ليست لديك صلاحية لعرض وارد هذا القسم.")
        return redirect("helpdesk:my_inbox")

    status = request.GET.get("status", "")  # فاضي = الكل
    cat_slug = request.GET.get("cat")
    q = (request.GET.get("q") or "").strip()

    qs = dept.tickets.all()

    if status:
        qs = qs.filter(status=status)

    if cat_slug:
        qs = qs.filter(category__slug=cat_slug)

    if q:
        qs = qs.filter(
            Q(subject__icontains=q)
            | Q(related_ref__icontains=q)
            | Q(tags__name__icontains=q)
        ).distinct()

    ctx = {
        "department": dept,
        "tickets": qs.select_related(
            "assigned_to", "requester", "category"
        ).prefetch_related("tags")[:500],
        "status": status,
        "categories": dept.categories.filter(is_active=True).order_by("order", "name"),
        "selected_cat": cat_slug,
        "q": q,
        "status_choices": Ticket.Status.choices,
    }
    return render(request, "helpdesk/department_inbox_uni.html", ctx)


# ===================== ANALYTICS / DASHBOARD / SEARCH =====================

@login_required
def dashboard(request):
    by_status = Ticket.objects.values("status").annotate(c=Count("id")).order_by()
    by_dept = (
        Ticket.objects.values("department__name")
        .annotate(c=Count("id"))
        .order_by("department__name")
    )

    duration = ExpressionWrapper(
        F("resolved_at") - F("created_at"), output_field=DurationField()
    )
    avg_res_hours = Ticket.objects.filter(resolved_at__isnull=False).aggregate(
        h=Avg(duration)
    )
    avg_hours = (
        round((avg_res_hours["h"].total_seconds() / 3600.0), 2)
        if avg_res_hours["h"]
        else 0
    )

    ctx = {
        "by_status": list(by_status),
        "by_dept": list(by_dept),
        "avg_hours": avg_hours,
    }
    return render(request, "helpdesk/dashboard.html", ctx)


@login_required
def search(request):
    """
    بحث في كل التذاكر:
    - العنوان
    - رقم التذكرة
    - مرجع الحجز / PNR
    - اسم/يوزر الطالب والمسؤول
    - التاجز
    مع فلاتر: القسم + الحالة
    """
    q = (request.GET.get("q") or "").strip()
    status = (request.GET.get("status") or "").strip()
    dept_slug = (request.GET.get("dept") or "").strip()

    qs = Ticket.objects.all()

    # فلتر القسم
    if dept_slug:
        qs = qs.filter(department__slug=dept_slug)

    # فلتر الحالة
    if status:
        qs = qs.filter(status=status)

    # فلتر كلمة البحث
    if q:
        qs = qs.filter(
            Q(subject__icontains=q)
            | Q(id__icontains=q)
            | Q(related_ref__icontains=q)
            | Q(requester__username__icontains=q)
            | Q(requester__first_name__icontains=q)
            | Q(requester__last_name__icontains=q)
            | Q(assigned_to__username__icontains=q)
            | Q(tags__name__icontains=q)
        ).distinct()

    departments = Department.objects.filter(is_active=True).order_by("name")

    ctx = {
        "q": q,
        "status": status,
        "dept_slug": dept_slug,
        "departments": departments,
        "status_choices": Ticket.Status.choices,
        "tickets": qs.select_related(
            "department", "requester", "assigned_to"
        ).prefetch_related("tags").order_by("-created_at")[:500],
    }
    return render(request, "helpdesk/search.html", ctx)

@login_required
def export_csv(request):
    since = timezone.now() - timezone.timedelta(days=90)
    qs = Ticket.objects.filter(created_at__gte=since).select_related(
        "department", "requester", "assigned_to"
    )

    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = "attachment; filename=tickets_export.csv"

    writer = csv.writer(response)
    writer.writerow(
        [
            "ID",
            "Subject",
            "Department",
            "Status",
            "Priority",
            "Requester",
            "Assignee",
            "Tags",
            "Created",
            "ResolvedAt",
            "SLA_Due",
        ]
    )

    for t in qs.prefetch_related("tags"):
        tags = ",".join(t.tags.values_list("name", flat=True))
        writer.writerow(
            [
                t.id,
                t.subject,
                t.department.name,
                t.status,
                t.priority,
                getattr(t.requester, "username", ""),
                getattr(t.assigned_to, "username", ""),
                tags,
                t.created_at,
                t.resolved_at,
                t.sla_due_at,
            ]
        )

    return response


# ===================== TICKETS CRUD =====================

@login_required
def ticket_create(request):
    if request.method == "POST":
        form = TicketForm(request.POST, request.FILES)
        if form.is_valid():
            ticket: Ticket = form.save(commit=False)
            ticket.requester = request.user

            ct = form.cleaned_data.get("related_model")
            rid = form.cleaned_data.get("related_id")
            if ct and rid:
                ticket.related_content_type = ct
                ticket.related_object_id = rid

            ticket.save()
            ticket.watchers.add(request.user)

            tags = form.cleaned_data.get("tags")
            if tags:
                ticket.tags.set(tags)

            body = form.cleaned_data.get("body")
            msg = TicketMessage.objects.create(
                ticket=ticket, sender=request.user, body=body
            )

            att = form.cleaned_data.get("attachment")
            if att:
                TicketAttachment.objects.create(
                    message=msg, uploaded_by=request.user, file=att
                )

            messages.success(request, "تم إنشاء التذكرة بنجاح.")
            return redirect(ticket.get_absolute_url())
    else:
        form = TicketForm()
        dept_slug = request.GET.get("department")
        subj = request.GET.get("subject")
        r_app = request.GET.get("related_app")
        r_model = request.GET.get("related_model")
        r_id = request.GET.get("related_id")

        if dept_slug:
            try:
                dept = Department.objects.get(slug=dept_slug)
                form.fields["department"].initial = dept
                form.fields["category"].queryset = TicketCategory.objects.filter(
                    department=dept, is_active=True
                ).order_by("order", "name")
            except Department.DoesNotExist:
                pass

        if subj:
            form.fields["subject"].initial = subj

        if r_app and r_model and r_id and r_id.isdigit():
            try:
                from django.contrib.contenttypes.models import ContentType

                ct = ContentType.objects.get(app_label=r_app, model=r_model)
                form.fields["related_model"].initial = ct
                form.fields["related_id"].initial = int(r_id)
            except Exception:
                pass

    return render(request, "helpdesk/ticket_create.html", {"form": form})


@login_required
def ticket_detail(request, pk: int):
    ticket = get_object_or_404(Ticket, pk=pk)

    if not can_view_ticket(request.user, ticket):
        messages.error(request, "ليست لديك صلاحية لعرض هذه التذكرة.")
        return redirect("helpdesk:my_inbox")

    if request.method == "POST":
        form = TicketReplyForm(
            request.POST, request.FILES, department=ticket.department
        )
        if form.is_valid() and can_reply_ticket(request.user, ticket):
            reply: TicketMessage = form.save(commit=False)
            reply.ticket = ticket
            reply.sender = request.user
            reply.save()

            att = form.cleaned_data.get("attachment")
            if att:
                TicketAttachment.objects.create(
                    message=reply, uploaded_by=request.user, file=att
                )

            canned = form.cleaned_data.get("canned")
            if canned and canned.body:
                reply.body = (reply.body + "\n\n" + canned.body).strip()
                reply.save(update_fields=["body"])

            usernames = set(MENTION_RE.findall(reply.body or ""))
            if usernames:
                from django.contrib.auth import get_user_model

                U = get_user_model()
                for u in U.objects.filter(username__in=list(usernames)):
                    ticket.watchers.add(u)

            ticket.updated_at = timezone.now()
            ticket.save(update_fields=["updated_at"])

            messages.success(request, "تم إرسال الرسالة.")
            return redirect(ticket.get_absolute_url())
    else:
        form = TicketReplyForm(department=ticket.department)

    ctx = {
        "ticket": ticket,
        "messages": ticket.messages.select_related("sender").prefetch_related(
            "attachments"
        ),
        "form": form,
        "status_choices": Ticket.Status.choices,
    }
    return render(request, "helpdesk/ticket_detail.html", ctx)


@login_required
def assign_me(request, pk: int):
    ticket = get_object_or_404(Ticket, pk=pk)

    if not is_dept_member(request.user, ticket.department):
        messages.error(request, "لا يمكنك إسناد تذكرة على قسم لست عضوًا به.")
        return redirect(ticket.get_absolute_url())

    ticket.assigned_to = request.user
    ticket.save(update_fields=["assigned_to", "updated_at"])

    messages.success(request, "تم إسناد التذكرة لك.")
    return redirect(ticket.get_absolute_url())


@login_required
def change_status(request, pk: int, new_status: str):
    ticket = get_object_or_404(Ticket, pk=pk)

    if not is_dept_member(request.user, ticket.department) and request.user != ticket.requester:
        messages.error(request, "لا تملك صلاحية تغيير الحالة.")
        return redirect(ticket.get_absolute_url())

    valid = {c for c, _ in Ticket.Status.choices}
    if new_status not in valid:
        messages.error(request, "حالة غير صحيحة.")
        return redirect(ticket.get_absolute_url())

    if new_status == Ticket.Status.RESOLVED and ticket.resolved_at is None:
        ticket.resolved_at = timezone.now()

    if ticket.status == Ticket.Status.RESOLVED and new_status != Ticket.Status.RESOLVED:
        ticket.resolved_at = None

    ticket.status = new_status
    ticket.save(update_fields=["status", "updated_at", "resolved_at"])

    messages.success(request, "تم تحديث حالة التذكرة.")
    return redirect(ticket.get_absolute_url())


@login_required
def ticket_messages_partial(request, pk: int):
    ticket = get_object_or_404(Ticket, pk=pk)

    if not can_view_ticket(request.user, ticket):
        return HttpResponse("", status=403)

    ctx = {
        "ticket": ticket,
        "messages": ticket.messages.select_related("sender").prefetch_related(
            "attachments"
        ),
    }
    return render(request, "helpdesk/_messages_partial.html", ctx)


# ===================== EXTRA TOOLS (HTMX CATEGORY OPTIONS) =====================

@login_required
def category_options(request):
    """
    Endpoint بسيط يرجّع <select> للفئات بناءً على القسم (يُستخدم مع HTMX)
    """
    dept_id = request.GET.get("dept_id")

    options = ['<select name="category" id="id_category">']
    options.append('<option value="">— اختر الفئة —</option>')

    if dept_id and dept_id.isdigit():
        qs = TicketCategory.objects.filter(
            department_id=int(dept_id), is_active=True
        ).order_by("order", "name")

        for c in qs:
            options.append(f'<option value="{c.id}">{c.name}</option>')

    options.append("</select>")
    return HttpResponse("".join(options))
