#include <cstdio>
#include <cmath>

#define AC 0
#define WA 1
#define ERROR -1

int spj(FILE *std_input, FILE *user_output);

void close_file(FILE *f){
    if(f != NULL) fclose(f);
}

int main(int argc, char *args[]){
    // Variable declaration
    int result;
    FILE *std_input = NULL, *user_output = NULL;
    
    // Check the number of arguments
    if(argc != 3){
        printf("Wrong format! Usage: spj std.in user.out\n");
        return ERROR;
    }

    // Acquire the file of std input and user output
    std_input = fopen(args[1], "r");
    user_output = fopen(args[2], "r");

    // Check the std input and user output
    if(std_input == NULL || user_output == NULL){
        if(std_input == NULL)
            printf("Failed to open std input file\n");
        if(std_input == NULL)
            printf("Failed to open user output file\n");

        close_file(std_input);
        close_file(user_output);
        return ERROR;
    }

    // Acquire the result
    result = spj(std_input, user_output);
    printf("%d\n", result);

    // Close file and return
    close_file(std_input);
    close_file(user_output);
    return result;
}

int spj(FILE *std_input, FILE *user_output){
    /*
      arguments: 
        - std_input, file pointer of std input
        - user_output, file pointer of user output

      return: 
        - if user ans is correct, return AC
        - if user ans is wrong, return WA
        - if catch error when run spj code, return ERROR
      
      demo:
        double a, b, std_ans, user_ans;
        
        fscanf(std_input, "%lf %lf", &a, &b);
        fscanf(user_output, "%lf", &user_ans);
        
        std_ans = a * b;
        if(abs(std_ans-user_ans) < 1e-6)
            return AC;
        else
            return WA;
     */
    double a, b, std_ans, user_ans;
    fscanf(std_input, "%lf %lf", &a, &b);
    fscanf(user_output, "%lf", &user_ans);
    std_ans = a * b;
    if(abs(std_ans-user_ans) < 1e-6) return AC;
    else return WA;
}