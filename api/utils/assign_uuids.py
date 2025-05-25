# exec(open('api/utils/assign_uuids.py').read())
import uuid
from api import models


def run():
    weekly_reports = models.WeeklyReports.objects.all()
    for report in weekly_reports:
        for activity in report.activities:
            new_id = uuid.uuid4()
            activity.update({"id": str(new_id)})
            print(new_id)
        report.save()

run()