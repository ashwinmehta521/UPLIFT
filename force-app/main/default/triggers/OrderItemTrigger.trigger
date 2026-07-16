trigger OrderItemTrigger on OrderItem (after insert, after update, after delete, after undelete) {
    if (Trigger.isInsert) {
        OrderItemTriggerHandler.handleAfterInsert(Trigger.new);
    } else if (Trigger.isUpdate) {
        OrderItemTriggerHandler.handleAfterUpdate(Trigger.new, Trigger.old);
    } else if (Trigger.isDelete) {
        OrderItemTriggerHandler.handleAfterDelete(Trigger.old);
    } else if (Trigger.isUndelete) {
        OrderItemTriggerHandler.handleAfterUndelete(Trigger.new);
    }
}
