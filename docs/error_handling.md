
1.Error handling must be performed before ending the current turn and initiating the next term

This alternative flow is  possible only when the toggle toggle live_board_check toggle is on
    This toggle controls whether or not to check for cv returned board state
    By default, when the user is not connected to the cv service, this check should not be performed
    WHen user is conencted to cv service, toggle this off enables user to still play when the cv is not configured

This alternative flow is triggered when the cv captured fen string is
    1.invalid
    2.not legal (more than one move change or placed in a not allowed square)
    
    
Client: 
Displays pop up message: board out of sync, 
This is caused by misplaced move or low cv confidence 
user click on x to exit 

system rejects the move
client stays the same and do not render the new move

the board ignores the new move request
client stays the same

this alternative flow ends

if user press end turn this is repeated until the current board state syncs up


