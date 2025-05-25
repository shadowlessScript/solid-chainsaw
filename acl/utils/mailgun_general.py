import requests
def send_mail(name, email, subject, message):
	send =  requests.post(
			"https://api.mailgun.net/v3/communications.youthadapt.africa/messages",
			auth=("api", "key-615596a3eb7952ba602d1aef3301c2b1"),
			data={"from": "Nairobi RRI Platform <no-reply@communications.youthadapt.africa>",
				"to": f"{name} <{email}>",
				"subject": subject,
				"text": message
    		})
 
	send_status = send.status_code

	if send_status == 200:
		return True
	else:
		return False

# You can see a record of this email in your logs: https://app.mailgun.com/app/logs.

# You can send up to 300 emails/day from this sandbox server.
# Next, you should add your own domain so you can send 10000 emails/month for free.