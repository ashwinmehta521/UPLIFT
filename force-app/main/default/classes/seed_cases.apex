// Anonymous Apex: Seed 10 fake Service Cloud Cases
// Run via Setup -> Developer Console -> Debug -> Open Execute Anonymous Window
// Paste this in, hit Execute

List<Case> casesToInsert = new List<Case>();

casesToInsert.add(new Case(
    Subject = 'Unable to log in to customer portal',
    Description = 'Customer reports they cannot log in despite resetting password twice. Getting \'invalid credentials\' error every time. Has tried on two different browsers.',
    Priority = 'High',
    Status = 'New',
    Origin = 'Web'
));

casesToInsert.add(new Case(
    Subject = 'Billing charged twice this month',
    Description = 'Customer was charged $499 twice on the same invoice date. Extremely frustrated, threatening to cancel subscription. Needs urgent refund.',
    Priority = 'High',
    Status = 'New',
    Origin = 'Phone'
));

casesToInsert.add(new Case(
    Subject = 'Feature request: dark mode',
    Description = 'Customer would like a dark mode option added to the dashboard. Not urgent, just a nice-to-have suggestion.',
    Priority = 'Low',
    Status = 'New',
    Origin = 'Email'
));

casesToInsert.add(new Case(
    Subject = 'Data export stuck at 0%',
    Description = 'Customer tried exporting a report 3 times, it hangs at 0% and never completes. This is blocking their month-end reporting deadline tomorrow.',
    Priority = 'High',
    Status = 'New',
    Origin = 'Web'
));

casesToInsert.add(new Case(
    Subject = 'Question about API rate limits',
    Description = 'Customer wants to understand what the rate limits are for their current plan tier before scaling up their integration.',
    Priority = 'Medium',
    Status = 'New',
    Origin = 'Email'
));

casesToInsert.add(new Case(
    Subject = 'Mobile app crashes on startup',
    Description = 'Since the latest app update, the mobile app crashes immediately on launch for iOS users. Multiple customers affected.',
    Priority = 'High',
    Status = 'New',
    Origin = 'Phone'
));

casesToInsert.add(new Case(
    Subject = 'Typo on invoice PDF',
    Description = 'Customer noticed their company name is misspelled on the generated invoice PDF. Minor cosmetic issue.',
    Priority = 'Low',
    Status = 'New',
    Origin = 'Email'
));

casesToInsert.add(new Case(
    Subject = 'Integration with third-party tool failing silently',
    Description = 'Customer\'s Zapier integration stopped syncing data 3 days ago with no error message. They didn\'t notice until data was missing from reports. Very unhappy about the silent failure.',
    Priority = 'Medium',
    Status = 'New',
    Origin = 'Web'
));

casesToInsert.add(new Case(
    Subject = 'Request to increase user seat limit',
    Description = 'Customer wants to add 15 more seats to their current plan. Straightforward upsell/account request.',
    Priority = 'Medium',
    Status = 'New',
    Origin = 'Phone'
));

casesToInsert.add(new Case(
    Subject = 'Account locked after failed payment',
    Description = 'Customer\'s card expired and account got locked. They\'ve updated their card but account is still locked 24 hours later. They have a team of 20 people unable to work.',
    Priority = 'High',
    Status = 'New',
    Origin = 'Phone'
));

insert casesToInsert;

System.debug('Inserted ' + casesToInsert.size() + ' fake cases.');
for (Case c : casesToInsert) {
    System.debug(c.Id + ' -> ' + c.Subject);
}
