import collections
import smtplib
import ssl
import threading

from db.models import NotificationsSent
from db.session import get_session
from utils.log import get_logger
from utils.settings import get_settings

logger = get_logger()
settings = get_settings()


class Notifications:
    def __init__(self) -> None:
        """
        Initialize the Notifications system.

        Starts a background thread that processes the email notification queue

        Returns:
            None
        """

        self.__queue = collections.deque()

        def handler() -> None:
            threading.Timer(3.0, handler).start()

            while len(self.__queue) > 0:
                notification = self.__queue.popleft()

                if (
                    settings.API_SMTP_HOST
                    and settings.API_SMTP_USERNAME
                    and settings.API_SMTP_PASSWORD
                ):
                    self.__notification_send_email(
                        to_emails=notification["to_emails"],
                        subject=notification["subject"],
                        message=notification["message"],
                    )

        handler()

    def add(self, to_emails: list, subject: str, message: str) -> None:
        """
        Queue an email notification to be sent later.

        Parameters:
            to_emails (list): List of recipient email addresses.
            subject (str): The subject of the email.
            message (str): The body of the email.

        Returns:
            None
        """

        if not settings.API_SMTP_HOST:
            logger.warning(
                "SMTP host is not configured. Email notifications will not be sent."
            )
            return

        self.__queue.append(
            {
                "to_emails": to_emails,
                "subject": subject,
                "message": message,
            }
        )

    def __notification_send_email(
        self, to_emails: list, subject: str, message: str
    ) -> None:
        """
        Send an email notification.

        Parameters:
            to_emails (list): List of recipient email addresses.
            subject (str): The subject of the email.
            message (str): The body of the email.

        Returns:
            None
        """

        try:
            context = ssl.create_default_context()
            server = smtplib.SMTP(settings.API_SMTP_HOST, settings.API_SMTP_PORT)
            server.starttls(context=context)
            server.login(settings.API_SMTP_USERNAME, settings.API_SMTP_PASSWORD)

            for email in to_emails:
                mail_to_send = f"From: {settings.NOTIFICATION_MAIL_SENDER_BRANDING} <{settings.API_SMTP_SENDER}>\nTo: {email}\nSubject: {subject}\n\n{message}"
                server.sendmail(settings.API_SMTP_SENDER, to_emails, mail_to_send)
                logger.info(f"Email sent to {', '.join(to_emails)}")
        except Exception as e:
            logger.error(f"Error sending email to {", ".join(to_emails)}: {e}")

    def send_email_verification(self, to_email: str) -> None:
        """
        Send an email verification notification.

        Parameters:
            to_email (str): The recipient's email address.

        Returns:
            None
        """

        self.add(
            to_emails=[to_email],
            subject=settings.NOTIFICATION_MAIL_UPDATED["subject"],
            message=settings.NOTIFICATION_MAIL_UPDATED["message"],
        )

    def send_transcription_finished(self, to_email: str) -> None:
        """
        Send a transcription finished notification.

        Parameters:
            to_email (str): The recipient's email address.

        Returns:
            None
        """

        self.add(
            to_emails=[to_email],
            subject=settings.NOTIFICATION_MAIL_TRANSCRIPTION_FINISHED["subject"],
            message=settings.NOTIFICATION_MAIL_TRANSCRIPTION_FINISHED["message"],
        )

    def send_transcription_failed(self, to_email: str) -> None:
        """
        Send a transcription failed notification.

        Parameters:
            to_email (str): The recipient's email address.

        Returns:
            None
        """

        self.add(
            to_emails=[to_email],
            subject=settings.NOTIFICATION_MAIL_TRANSCRIPTION_FAILED["subject"],
            message=settings.NOTIFICATION_MAIL_TRANSCRIPTION_FAILED["message"],
        )

    def send_job_deleted(self, to_email: str) -> None:
        """
        Send a job deleted notification.

        Parameters:
            to_email (str): The recipient's email address.

        Returns:
            None
        """

        self.add(
            to_emails=[to_email],
            subject=settings.NOTIFICATION_MAIL_TRANSCRIPTION_DELETED["subject"],
            message=settings.NOTIFICATION_MAIL_TRANSCRIPTION_DELETED["message"],
        )

    def send_job_to_be_deleted(self, to_email: str) -> None:
        """
        Send a job to be deleted notification.

        Parameters:
            to_email (str): The recipient's email address.

        Returns:
            None
        """

        self.add(
            to_emails=[to_email],
            subject=settings.NOTIFICATION_MAIL_TRANSCRIPTION_TO_BE_DELETED["subject"],
            message=settings.NOTIFICATION_MAIL_TRANSCRIPTION_TO_BE_DELETED["message"],
        )

    def send_new_user_created(self, to_email: str, username: str) -> None:
        """
        Send a new user created notification to the admin.

        Parameters:
            to_email (str): The recipient's email address.

        Returns:
            None
        """

        self.add(
            to_emails=[to_email],
            subject=settings.NOTIFICATION_MAIL_NEW_USER_CREATED["subject"],
            message=settings.NOTIFICATION_MAIL_NEW_USER_CREATED["message"].format(
                username=username
            ),
        )

    def notification_sent_record_add(
        self, user_id: str, uuid: str, notification_type: str
    ) -> None:
        """
        Record that a notification has been sent to avoid duplicates.

        Parameters:
            user_id (str): The ID of the user.
            uuid (str): The UUID of the job or entity.
            notification_type (str): The type of notification sent.

        Returns:
            None
        """

        with get_session() as session:
            notification = NotificationsSent(
                user_id=user_id,
                uuid=uuid,
                notification_type=notification_type,
            )
            session.add(notification)
            session.commit()

    def notification_sent_record_exists(
        self, user_id: str, uuid: str, notification_type: str
    ) -> bool:
        """
        Check if a notification has already been sent.

        Parameters:
            user_id (str): The ID of the user.
            uuid (str): The UUID of the job or entity.
            notification_type (str): The type of notification sent.

        Returns:
            bool: True if the notification has been sent, False otherwise.
        """

        with get_session() as session:
            record = (
                session.query(NotificationsSent)
                .filter_by(
                    user_id=user_id,
                    uuid=uuid,
                    notification_type=notification_type,
                )
                .first()
            )

            return record is not None

    def notification_send_account_activated(self, to_email: str) -> None:
        """
        Send an account activated notification.

        Parameters:
            to_email (str): The recipient's email address.

        Returns:
            None
        """

        self.add(
            to_emails=[to_email],
            subject=settings.NOTIFICATION_MAIL_ACCOUNT_ACTIVATED["subject"],
            message=settings.NOTIFICATION_MAIL_ACCOUNT_ACTIVATED["message"],
        )


notifications = Notifications()
