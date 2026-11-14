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
    DepartmentMembership,
    Ticket,
    TicketMessage,
    TicketAttachment,
    TicketCategory,
)
from .forms import TicketForm, TicketReplyForm
from .permissions import (
    can_view_ticket, can_reply_ticket, is_dept_member, can_forward, can_see_internal,
    allowed_department_slugs, visible_tickets,
)

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
    vis = visible_tickets(request.user)
    by_status = vis.values("status").annotate(c=Count("id")).order_by()
    by_dept = (
        vis.values("department__name")
        .annotate(c=Count("id"))
        .order_by("department__name")
    )

    duration = ExpressionWrapper(
        F("resolved_at") - F("created_at"), output_field=DurationField()
    )
    avg_res_hours = vis.filter(resolved_at__isnull=False).aggregate(
        h=Avg(duration)
    )
    avg_hours = (
        round((avg_res_hours["h"].total_seconds() / 3600.0), 2)
        if avg_res_hours["h"]
        else 0
    )

    q = (request.GET.get("q") or "").strip()
    status = (request.GET.get("status") or "").strip()
    dept_slug = (request.GET.get("department") or request.GET.get("dept") or "").strip()
    priority = (request.GET.get("priority") or "").strip()
    lst = vis
    if dept_slug:
        lst = lst.filter(department__slug=dept_slug)
    if status:
        lst = lst.filter(status=status)
    if priority:
        lst = lst.filter(priority=priority)
    if q:
        lst = lst.filter(
            Q(subject__icontains=q) | Q(id__icontains=q) | Q(related_ref__icontains=q)
            | Q(requester__username__icontains=q) | Q(assigned_to__username__icontains=q)
        ).distinct()
    labels = dict(Ticket.Status.choices)

    S = Ticket.Status
    counts = {r["status"]: r["c"] for r in by_status}
    grp = lambda *codes: sum(counts.get(c, 0) for c in codes)

    ctx = {
        "total_count": sum(counts.values()),
        "open_count": grp(S.OPEN, S.IN_PROGRESS, S.PENDING_ENTRY, S.CALLS),
        "pending_count": grp(S.PENDING, S.WAITING_THIRD_PARTY, S.ON_HOLD),
        "resolved_count": grp(S.RESOLVED, S.CANCELLED),
        "by_status": [{**r, "label": labels.get(r["status"], r["status"])} for r in by_status],
        "by_dept": list(by_dept),
        "avg_hours": avg_hours,
        "q": q, "status": status, "dept_slug": dept_slug,
        "status_choices": Ticket.Status.choices,
        "departments": Department.objects.filter(is_active=True).order_by("name"),
        "tickets": lst.select_related("department", "requester", "assigned_to").prefetch_related("tags").order_by("-created_at")[:300],
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

    qs = visible_tickets(request.user)

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
    qs = visible_tickets(request.user).filter(created_at__gte=since).select_related(
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
        form = TicketForm(request.POST, request.FILES, user=request.user)
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

            for att in form.cleaned_data.get("attachment") or []:
                TicketAttachment.objects.create(
                    message=msg, uploaded_by=request.user, file=att
                )

            messages.success(request, "تم إنشاء التذكرة بنجاح.")
            return redirect(ticket.get_absolute_url())
    else:
        form = TicketForm(user=request.user)
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

        if request.GET.get("related_ref"):
            form.fields["related_ref"].initial = request.GET["related_ref"][:100]
        if request.GET.get("related_url"):
            form.fields["related_url"].initial = request.GET["related_url"][:200]

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
            if not can_see_internal(request.user, ticket):
                reply.is_internal_note = False       # only staff may write internal notes
            reply.save()
            if not reply.is_internal_note:
                if request.user.pk == ticket.requester_id:
                    if ticket.status == Ticket.Status.PENDING:
                        set_status(ticket, Ticket.Status.IN_PROGRESS if ticket.assigned_to_id else Ticket.Status.OPEN,
                                   request.user, auto=True)
                elif ticket.status == Ticket.Status.OPEN:
                    set_status(ticket, Ticket.Status.IN_PROGRESS, request.user, auto=True)

            for att in form.cleaned_data.get("attachment") or []:
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

    staff_view = can_see_internal(request.user, ticket)
    msgs = ticket.messages.select_related("sender").prefetch_related("attachments")
    if not staff_view:
        msgs = msgs.filter(is_internal_note=False)

    ctx = {
        "ticket": ticket,
        "thread": msgs,
        "form": form,
        "status_choices": Ticket.Status.choices,
        "staff_view": staff_view,
        "assignees": eligible_assignees(ticket.department, exclude=ticket.assigned_to) if staff_view else [],
    }
    if ticket.parent_id and is_dept_member(request.user, ticket.parent.department):
        ctx["parent"] = ticket.parent
    if can_forward(request.user, ticket):
        first = ticket.messages.filter(is_internal_note=False).order_by("created_at").first()
        ctx["can_forward"] = True
        ctx["forward_departments"] = Department.objects.filter(is_active=True, slug__in=["operations", "fft"])
        ctx["first_body"] = first.body if first else ""
        ctx["children"] = ticket.children.select_related("department").prefetch_related("messages__attachments", "messages__sender").order_by("created_at")
    return render(request, "helpdesk/ticket_detail.html", ctx)


@login_required
def assign_me(request, pk: int):
    ticket = get_object_or_404(Ticket, pk=pk)

    if not is_dept_member(request.user, ticket.department):
        messages.error(request, "لا يمكنك إسناد تذكرة على قسم لست عضوًا به.")
        return redirect(ticket.get_absolute_url())

    ticket.assigned_to = request.user
    ticket.save(update_fields=["assigned_to", "updated_at"])
    if ticket.status == Ticket.Status.OPEN:
        set_status(ticket, Ticket.Status.IN_PROGRESS, request.user, auto=True)
        if ticket.requester_id != request.user.id:
            _bell(ticket.requester, f"تم استلام طلبك #{ticket.pk} بواسطة {request.user} (قيد التنفيذ).", ticket.get_absolute_url())

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

    staff = is_dept_member(request.user, ticket.department) or can_see_internal(request.user, ticket)
    if not staff and new_status not in (Ticket.Status.RESOLVED, Ticket.Status.CANCELLED, Ticket.Status.OPEN):
        messages.error(request, "الحالة دي بيحددها القسم.")
        return redirect(ticket.get_absolute_url())

    changed = set_status(ticket, new_status, request.user)

    if changed and ticket.requester_id != request.user.id and ticket.requester.is_active:
        from core.models import Notification
        Notification.objects.create(
            to_user=ticket.requester, target_url=ticket.get_absolute_url(),
            message=f"تم تحديث حالة الطلب #{ticket.pk} إلى {ticket.get_status_display()}: {ticket.subject}",
        )

    messages.success(request, "تم تحديث حالة التذكرة.")
    return redirect(ticket.get_absolute_url())


@login_required
def ticket_messages_partial(request, pk: int):
    ticket = get_object_or_404(Ticket, pk=pk)

    if not can_view_ticket(request.user, ticket):
        return HttpResponse("", status=403)

    msgs = ticket.messages.select_related("sender").prefetch_related("attachments")
    if not can_see_internal(request.user, ticket):
        msgs = msgs.filter(is_internal_note=False)
    ctx = {"ticket": ticket, "thread": msgs}
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


# ---------------------------------------------------------------------------
# CS forwards a sales request to Operations / FFT, and relays their answer back to the agent
# ---------------------------------------------------------------------------
@login_required
def ticket_forward(request, pk: int):
    ticket = get_object_or_404(Ticket, pk=pk)
    if request.method != "POST" or not can_forward(request.user, ticket):
        messages.error(request, "التحويل متاح لـ CS فقط.")
        return redirect("helpdesk:ticket_detail", pk=ticket.pk)

    dept = Department.objects.filter(is_active=True, slug=request.POST.get("department"), slug__in=["operations", "fft"]).first()
    body = (request.POST.get("body") or "").strip()
    if not dept or not body:
        messages.error(request, "اختار القسم (أوبريشن أو FFT) واكتب الرسالة.")
        return redirect("helpdesk:ticket_detail", pk=ticket.pk)

    child = Ticket.objects.create(
        subject=f"[CS #{ticket.pk}] {ticket.subject}"[:200], department=dept, requester=request.user,
        parent=ticket, priority=ticket.priority,
        related_content_type=ticket.related_content_type, related_object_id=ticket.related_object_id,
        related_ref=ticket.related_ref, related_url=ticket.related_url,
    )
    child.watchers.add(request.user)
    TicketMessage.objects.create(ticket=child, sender=request.user, body=body)
    _system_note(ticket, request.user, f"تم التحويل إلى {dept.name} (طلب #{child.pk}).")
    if ticket.assigned_to_id is None:
        ticket.assigned_to = request.user
        ticket.save(update_fields=["assigned_to", "updated_at"])
    if not ticket.is_closed:
        set_status(ticket, Ticket.Status.WAITING_THIRD_PARTY, request.user, auto=True)
    messages.success(request, f"تم التحويل إلى {dept.name}. هتلاقي ردهم تحت وتنقله للأجنت.")
    return redirect("helpdesk:ticket_detail", pk=ticket.pk)


@login_required
def ticket_relay(request, pk: int, msg_id: int):
    """Copy a public reply (and its files) from a forwarded request into the sales request."""
    ticket = get_object_or_404(Ticket, pk=pk)
    if request.method != "POST" or not can_forward(request.user, ticket):
        messages.error(request, "غير مسموح.")
        return redirect("helpdesk:ticket_detail", pk=ticket.pk)
    src = get_object_or_404(TicketMessage, pk=msg_id, ticket__parent=ticket, is_internal_note=False)
    note = (request.POST.get("note") or "").strip()
    body = f"رد {src.ticket.department.name}:\n{src.body}" + (f"\n\n{note}" if note else "")
    msg = TicketMessage.objects.create(ticket=ticket, sender=request.user, body=body)
    for att in src.attachments.all():
        TicketAttachment.objects.create(message=msg, uploaded_by=request.user, file=att.file)
    ticket.updated_at = timezone.now()
    ticket.save(update_fields=["updated_at"])
    messages.success(request, "تم نقل الرد للأجنت.")
    return redirect("helpdesk:ticket_detail", pk=ticket.pk)


# ---------------------------------------------------------------------------
# Hand over cases (end of shift / leave / reassignment)
# ---------------------------------------------------------------------------
CLOSED = Ticket.CLOSED_STATUSES


def set_status(ticket, new_status, actor, auto=False):
    """Single place that changes a request's status: resolved_at, a silent log line, and the parent follow-up."""
    old = ticket.status
    if new_status == old:
        return False
    if new_status == Ticket.Status.RESOLVED and ticket.resolved_at is None:
        ticket.resolved_at = timezone.now()
    if old == Ticket.Status.RESOLVED and new_status != Ticket.Status.RESOLVED:
        ticket.resolved_at = None
    ticket.status = new_status
    ticket.save(update_fields=["status", "updated_at", "resolved_at"])
    labels = dict(Ticket.Status.choices)
    _system_note(ticket, actor, f"الحالة: {labels.get(old, old)} ← {labels.get(new_status, new_status)}" + (" (تلقائي)" if auto else ""))

    # a request CS forwarded came back: when every forwarded request is closed, the sales request is back in CS's hands
    if new_status in Ticket.CLOSED_STATUSES and ticket.parent_id:
        parent = ticket.parent
        if parent.status == Ticket.Status.WAITING_THIRD_PARTY and not parent.children.exclude(status__in=Ticket.CLOSED_STATUSES).exists():
            set_status(parent, Ticket.Status.IN_PROGRESS, actor, auto=True)
            if parent.assigned_to_id and parent.assigned_to_id != actor.id:
                _bell(parent.assigned_to, f"القسم رد على الطلب #{ticket.pk} — رجع لك الطلب #{parent.pk}", parent.get_absolute_url())
    return True


def eligible_assignees(department, exclude=None):
    """Active members / leaders of the department, plus its manager (never viewers)."""
    from django.contrib.auth import get_user_model
    User = get_user_model()
    ids = set(DepartmentMembership.objects.filter(
        department=department, is_active=True, role__in=["member", "leader"]).values_list("user_id", flat=True))
    if department.manager_id:
        ids.add(department.manager_id)
    qs = User.objects.filter(pk__in=ids, is_active=True)
    return qs.exclude(pk=exclude.pk) if exclude else qs


def _can_move_tickets(user, ticket) -> bool:
    from .permissions import _is_manager
    return _is_manager(user) or is_dept_member(user, ticket.department)


def _system_note(ticket, sender, body):
    """Internal note written by the system (reassign / forward / hand-over): kept in the log, no notifications."""
    m = TicketMessage(ticket=ticket, sender=sender, is_internal_note=True, body=body)
    m._system_note = True
    m.save()
    return m


def _bell(to_user, message, url):
    from core.models import Notification
    Notification.objects.create(to_user=to_user, message=message, target_url=url)


@login_required
def ticket_assign(request, pk: int):
    """Move one request to a colleague of the same department."""
    from django.contrib.auth import get_user_model
    ticket = get_object_or_404(Ticket, pk=pk)
    if request.method != "POST" or not _can_move_tickets(request.user, ticket):
        messages.error(request, "غير مسموح.")
        return redirect("helpdesk:ticket_detail", pk=ticket.pk)
    target = eligible_assignees(ticket.department).filter(pk=request.POST.get("to_user") or 0).first()
    if not target:
        messages.error(request, "اختار زميل من نفس القسم.")
        return redirect("helpdesk:ticket_detail", pk=ticket.pk)
    old = ticket.assigned_to
    ticket.assigned_to = target
    ticket.save(update_fields=["assigned_to", "updated_at"])
    _system_note(ticket, request.user, f"تحويل الطلب من {old or 'بدون مسؤول'} إلى {target}.")
    if ticket.status == Ticket.Status.OPEN:
        set_status(ticket, Ticket.Status.IN_PROGRESS, request.user, auto=True)
    if target.pk != request.user.pk:
        _bell(target, f"اتحوّلك الطلب #{ticket.pk}: {ticket.subject}", ticket.get_absolute_url())
    messages.success(request, f"تم تحويل الطلب إلى {target}.")
    return redirect("helpdesk:ticket_detail", pk=ticket.pk)


@login_required
def handover(request):
    """End of shift: move all (or some) of my open requests to a colleague, or release them to the department."""
    from django.contrib.auth import get_user_model
    from .permissions import _is_manager
    User = get_user_model()
    me = request.user

    from_id = request.POST.get("from_user") or request.GET.get("from")
    from_user = me
    if from_id and str(from_id) != str(me.pk):
        other = get_object_or_404(User, pk=from_id)
        is_dept_manager = Department.objects.filter(
            manager=me, memberships__user=other, memberships__is_active=True).exists()
        if not (_is_manager(me) or is_dept_manager):
            messages.error(request, "تسليم شيفت موظف تاني متاح للمدير أو مدير القسم.")
            return redirect("helpdesk:my_inbox")
        from_user = other

    tickets = list(
        Ticket.objects.filter(assigned_to=from_user).exclude(status__in=CLOSED)
        .select_related("department", "requester").order_by("department__name", "-updated_at")
    )
    dept_ids = {t.department_id for t in tickets} or set(
        DepartmentMembership.objects.filter(user=from_user, is_active=True).values_list("department_id", flat=True))
    people = {}
    for d in Department.objects.filter(pk__in=dept_ids):
        for u in eligible_assignees(d, exclude=from_user):
            people[u.pk] = u

    if request.method == "POST":
        selected = set(request.POST.getlist("tickets"))
        to_id = request.POST.get("to_user") or ""
        note = (request.POST.get("note") or "").strip()
        chosen = [t for t in tickets if str(t.pk) in selected]
        if not chosen:
            messages.error(request, "اختار طلب واحد على الأقل.")
            return redirect(request.get_full_path())
        target = None
        if to_id:
            target = User.objects.filter(pk=to_id, is_active=True).first()
            if not target:
                messages.error(request, "الموظف المستلم غير موجود.")
                return redirect(request.get_full_path())
        moved, skipped = 0, []
        for t in chosen:
            if target and target.pk not in {u.pk for u in eligible_assignees(t.department)}:
                skipped.append(t)           # the receiver is not in that request's department
                continue
            t.assigned_to = target
            t.save(update_fields=["assigned_to", "updated_at"])
            if target and t.status == Ticket.Status.OPEN:
                set_status(t, Ticket.Status.IN_PROGRESS, me, auto=True)
            elif not target and t.status == Ticket.Status.IN_PROGRESS:
                set_status(t, Ticket.Status.OPEN, me, auto=True)      # back to the pool: anyone can take it
            where = f"إلى {target}" if target else "للقسم (من غير مسؤول)"
            _system_note(t, me, f"تسليم شيفت: من {from_user} {where}." + (f"\nملاحظة: {note}" if note else ""))
            moved += 1
        if target and moved:
            _bell(target, f"استلمت {moved} طلب من {from_user} (تسليم شيفت)" + (f" — {note}" if note else ""),
                  "/helpdesk/")
        if moved:
            messages.success(request, f"تم تسليم {moved} طلب" + (f" إلى {target}." if target else " للقسم."))
        if skipped:
            messages.warning(request, f"{len(skipped)} طلب ما اتنقلوش لأن المستلم مش من القسم بتاعهم.")
        return redirect("helpdesk:handover")

    managers_view = _is_manager(me) or Department.objects.filter(manager=me).exists()
    team = []
    if managers_view:
        team = list(User.objects.filter(
            pk__in=DepartmentMembership.objects.filter(is_active=True).values_list("user_id", flat=True), is_active=True
        ).order_by("first_name", "username"))
    return render(request, "helpdesk/handover.html", {
        "from_user": from_user, "tickets": tickets, "people": sorted(people.values(), key=lambda u: u.get_full_name() or u.username),
        "is_self": from_user.pk == me.pk, "team": team,
    })
