"""Bearer-authenticated Master Admin feedback routes."""

import json
from flask import Blueprint, g, jsonify, request
from services.master_admin_feedback import (
    FeedbackConflictError, get_feedback, list_feedback, update_feedback,
)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate field.")
        result[key] = value
    return result


def register_master_admin_feedback_api(
    app, *, get_connection, require_admin, no_store, audit,
):
    bp = Blueprint("master_admin_feedback", __name__)

    def response(payload, status=200):
        return no_store((jsonify(payload), status))

    def perform(operation, *, write=False):
        conn = None
        cur = None
        try:
            conn = get_connection()
            conn.set_session(readonly=not write, autocommit=False)
            cur = conn.cursor()
            result = operation(cur)
            if result is None:
                conn.rollback()
                return response({
                    "success": False, "error": "feedback_not_found",
                    "message": "Feedback was not found.",
                }, 404)
            if write:
                conn.commit()
            return response({"success": True, **result})
        except FeedbackConflictError:
            if conn is not None:
                conn.rollback()
            return response({
                "success": False, "error": "feedback_conflict",
                "message": "Feedback changed. Refresh before saving.",
            }, 409)
        except ValueError:
            if conn is not None:
                conn.rollback()
            return response({
                "success": False, "error": "invalid_feedback_request",
                "message": "Check the feedback request and try again.",
            }, 400)
        except Exception:
            if conn is not None:
                conn.rollback()
            app.logger.error("Master Admin feedback operation failed.")
            return response({
                "success": False, "error": "feedback_unavailable",
                "message": "Feedback is temporarily unavailable.",
            }, 503)
        finally:
            if cur is not None:
                cur.close()
            if conn is not None:
                conn.close()

    @bp.route("/api/master-admin/feedback", methods=["GET"])
    @require_admin
    def listing():
        allowed = {"status", "feedback_type", "limit", "offset"}
        if (
            set(request.args) - allowed
            or any(len(request.args.getlist(k)) != 1 for k in request.args)
        ):
            return response({"success": False, "error": "invalid_query"}, 400)
        try:
            limit = int(request.args.get("limit", "50"))
            offset = int(request.args.get("offset", "0"))
        except ValueError:
            return response({"success": False, "error": "invalid_query"}, 400)
        return perform(lambda cur: {
            "feedback": list_feedback(
                cur,
                status=request.args.get("status", "open"),
                feedback_type=request.args.get("feedback_type", ""),
                limit=limit, offset=offset,
            )
        })

    @bp.route("/api/master-admin/feedback/<int:feedback_id>", methods=["GET"])
    @require_admin
    def detail(feedback_id):
        def operation(cur):
            item = get_feedback(cur, feedback_id=feedback_id)
            return {"item": item} if item is not None else None
        return perform(operation)

    @bp.route("/api/master-admin/feedback/<int:feedback_id>", methods=["POST"])
    @require_admin
    def update(feedback_id):
        if request.mimetype != "application/json":
            return response({"success": False, "error": "json_required"}, 415)
        if request.content_length is not None and request.content_length > 65536:
            return response({"success": False, "error": "request_too_large"}, 413)
        body = request.stream.read(65537)
        if len(body) > 65536:
            return response({"success": False, "error": "request_too_large"}, 413)
        try:
            data = json.loads(body, object_pairs_hook=_unique_object)
            if not isinstance(data, dict) or set(data) != {
                "revision", "is_resolved", "action_taken_note",
            }:
                raise ValueError("Invalid fields.")
        except (ValueError, UnicodeDecodeError):
            return response({"success": False, "error": "invalid_json"}, 400)

        return perform(
            lambda cur: update_feedback(
                cur,
                feedback_id=feedback_id,
                actor_user_id=g.master_admin_api["master_admin_user_id"],
                revision=data["revision"],
                is_resolved=data["is_resolved"],
                action_taken_note=data["action_taken_note"],
                audit=audit,
            ),
            write=True,
        )

    app.register_blueprint(bp)
