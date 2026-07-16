@isTest
private class OrderItemTriggerHandlerTest {

    private static Account createAccount() {
        Account acct = new Account(Name = 'OrderItemTriggerHandlerTest Account');
        insert acct;
        return acct;
    }

    private static Id createPricebookEntry(Id pricebookId, Decimal unitPrice) {
        Product2 product = new Product2(Name = 'OrderItemTriggerHandlerTest Product', IsActive = true);
        insert product;

        PricebookEntry entry = new PricebookEntry(
            Pricebook2Id = pricebookId,
            Product2Id = product.Id,
            UnitPrice = unitPrice,
            IsActive = true
        );
        insert entry;
        return entry.Id;
    }

    private static Order createOrder(Id accountId, Id pricebookId) {
        Order ord = new Order(
            AccountId = accountId,
            Pricebook2Id = pricebookId,
            EffectiveDate = Date.today(),
            Status = 'Draft'
        );
        insert ord;
        return ord;
    }

    private static Decimal totalFor(Id orderId) {
        return [SELECT Total_Order_Price__c FROM Order WHERE Id = :orderId].Total_Order_Price__c;
    }

    @isTest
    static void testBulkInsertAcrossMultipleOrdersSumsCorrectly() {
        Id pricebookId = Test.getStandardPricebookId();
        Account acct = createAccount();
        Id pricebookEntryId = createPricebookEntry(pricebookId, 10);

        Integer orderCount = 4;
        Integer itemsPerOrder = 50; // 4 * 50 = 200 OrderItems in one transaction
        List<Order> orders = new List<Order>();
        for (Integer i = 0; i < orderCount; i++) {
            orders.add(new Order(
                AccountId = acct.Id,
                Pricebook2Id = pricebookId,
                EffectiveDate = Date.today(),
                Status = 'Draft'
            ));
        }
        insert orders;

        List<OrderItem> items = new List<OrderItem>();
        for (Order ord : orders) {
            for (Integer i = 0; i < itemsPerOrder; i++) {
                items.add(new OrderItem(
                    OrderId = ord.Id,
                    PricebookEntryId = pricebookEntryId,
                    Quantity = 1,
                    UnitPrice = 10
                ));
            }
        }
        System.assertEquals(200, items.size(), 'Test should exercise 200 OrderItems in a single DML.');

        Test.startTest();
        insert items;
        Test.stopTest();

        Map<Id, Order> updatedOrders = new Map<Id, Order>(
            [SELECT Id, Total_Order_Price__c FROM Order WHERE Id IN :orders]
        );
        for (Order ord : orders) {
            System.assertEquals(
                itemsPerOrder * 10,
                updatedOrders.get(ord.Id).Total_Order_Price__c,
                'Each order should total itemsPerOrder * unitPrice.'
            );
        }
    }

    @isTest
    static void testUpdatingQuantityAndUnitPriceRecalculatesTotal() {
        Id pricebookId = Test.getStandardPricebookId();
        Account acct = createAccount();
        Id pricebookEntryId = createPricebookEntry(pricebookId, 50);
        Order ord = createOrder(acct.Id, pricebookId);

        OrderItem item = new OrderItem(
            OrderId = ord.Id,
            PricebookEntryId = pricebookEntryId,
            Quantity = 2,
            UnitPrice = 50
        );
        insert item;
        System.assertEquals(100, totalFor(ord.Id), 'Initial total should be quantity * unit price.');

        Test.startTest();
        item.Quantity = 5;
        item.UnitPrice = 30;
        update item;
        Test.stopTest();

        System.assertEquals(150, totalFor(ord.Id), 'Total should reflect the updated quantity and unit price.');
    }

    @isTest
    static void testDeletingOneLineItemReducesTotal() {
        Id pricebookId = Test.getStandardPricebookId();
        Account acct = createAccount();
        Id pricebookEntryId = createPricebookEntry(pricebookId, 25);
        Order ord = createOrder(acct.Id, pricebookId);

        OrderItem item1 = new OrderItem(
            OrderId = ord.Id, PricebookEntryId = pricebookEntryId, Quantity = 2, UnitPrice = 25
        ); // 50
        OrderItem item2 = new OrderItem(
            OrderId = ord.Id, PricebookEntryId = pricebookEntryId, Quantity = 4, UnitPrice = 25
        ); // 100
        insert new List<OrderItem>{ item1, item2 };
        System.assertEquals(150, totalFor(ord.Id), 'Initial total should sum both line items.');

        Test.startTest();
        delete item2;
        Test.stopTest();

        System.assertEquals(50, totalFor(ord.Id), 'Total should drop by the deleted line item value.');
    }

    @isTest
    static void testDeletingLastLineItemLeavesOrderAtZero() {
        Id pricebookId = Test.getStandardPricebookId();
        Account acct = createAccount();
        Id pricebookEntryId = createPricebookEntry(pricebookId, 40);
        Order ord = createOrder(acct.Id, pricebookId);

        OrderItem item = new OrderItem(
            OrderId = ord.Id, PricebookEntryId = pricebookEntryId, Quantity = 3, UnitPrice = 40
        ); // 120
        insert item;
        System.assertEquals(120, totalFor(ord.Id));

        Test.startTest();
        delete item;
        Test.stopTest();

        System.assertEquals(
            0,
            totalFor(ord.Id),
            'Order with zero remaining line items should be rolled up to 0, not left null.'
        );
    }

    @isTest
    static void testUndeleteRestoresTotal() {
        Id pricebookId = Test.getStandardPricebookId();
        Account acct = createAccount();
        Id pricebookEntryId = createPricebookEntry(pricebookId, 60);
        Order ord = createOrder(acct.Id, pricebookId);

        OrderItem item = new OrderItem(
            OrderId = ord.Id, PricebookEntryId = pricebookEntryId, Quantity = 1, UnitPrice = 60
        );
        insert item;
        delete item;
        System.assertEquals(0, totalFor(ord.Id), 'Total should be 0 after delete.');

        Test.startTest();
        undelete item;
        Test.stopTest();

        System.assertEquals(60, totalFor(ord.Id), 'Total should be restored after undelete.');
    }
}
