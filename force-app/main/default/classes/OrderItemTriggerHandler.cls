public with sharing class OrderItemTriggerHandler {

    public static void handleAfterInsert(List<OrderItem> newItems) {
        recalculateOrderTotals(collectOrderIds(newItems, null));
    }

    public static void handleAfterUpdate(List<OrderItem> newItems, List<OrderItem> oldItems) {
        recalculateOrderTotals(collectOrderIds(newItems, oldItems));
    }

    public static void handleAfterDelete(List<OrderItem> oldItems) {
        recalculateOrderTotals(collectOrderIds(oldItems, null));
    }

    public static void handleAfterUndelete(List<OrderItem> newItems) {
        recalculateOrderTotals(collectOrderIds(newItems, null));
    }

    private static Set<Id> collectOrderIds(List<OrderItem> itemsA, List<OrderItem> itemsB) {
        Set<Id> orderIds = new Set<Id>();
        addOrderIds(orderIds, itemsA);
        addOrderIds(orderIds, itemsB);
        return orderIds;
    }

    private static void addOrderIds(Set<Id> orderIds, List<OrderItem> items) {
        if (items == null) {
            return;
        }
        for (OrderItem item : items) {
            if (item.OrderId != null) {
                orderIds.add(item.OrderId);
            }
        }
    }

    /**
     * Recomputes Total_Order_Price__c for every Order in orderIds as the SUM
     * of TotalPrice across its current OrderItems, using a single aggregate
     * query and a single DML update regardless of how many orders/items are
     * affected. Orders with no remaining OrderItems get 0, not null.
     */
    private static void recalculateOrderTotals(Set<Id> orderIds) {
        if (orderIds.isEmpty()) {
            return;
        }

        Map<Id, Decimal> totalByOrderId = new Map<Id, Decimal>();
        for (AggregateResult result : [
            SELECT OrderId, SUM(TotalPrice) total
            FROM OrderItem
            WHERE OrderId IN :orderIds
            GROUP BY OrderId
        ]) {
            totalByOrderId.put((Id) result.get('OrderId'), (Decimal) result.get('total'));
        }

        List<Order> ordersToUpdate = new List<Order>();
        for (Id orderId : orderIds) {
            Decimal total = totalByOrderId.containsKey(orderId) ? totalByOrderId.get(orderId) : 0;
            ordersToUpdate.add(new Order(Id = orderId, Total_Order_Price__c = total));
        }

        update ordersToUpdate;
    }
}
